"""mermaid 启发式语法校验（设计 D2）。

后端无 JS 运行时，不做完整 parse：只校验"一定会让前端渲染炸掉"的结构错误
（类型声明行缺失、参与者行格式、无消息箭头、混入自然语言散文）。
前端 mermaid.render 有 try/catch 兜底，两端双保险。
"""
import re

FENCE_RE = re.compile(r"```[ \t]*[a-zA-Z]*[ \t]*\n(.*?)(?:```|$)", re.S)

# 按长度降序排列，避免 "->>"" 被 "->" 抢先匹配
ARROW_TOKEN_RE = re.compile(r"(<<-->>|<<->>|-->>|->>|--x|-x|--\)|-\)|-->|->)")

PARTICIPANT_RE = re.compile(
    r"^(?:participant|actor)\s+(?P<name>\"[^\"]+\"|\S+)(?:\s+as\s+.+)?$", re.I
)

# sequenceDiagram 中允许的结构性关键字（其余行必须是箭头行或参与者行）
SEQ_KEYWORDS = (
    "autonumber", "activate", "deactivate", "note", "loop", "alt", "else",
    "opt", "par", "and", "critical", "option", "break", "rect", "end",
    "box", "link", "links", "create", "destroy",
)


def strip_fence(text: str) -> str:
    """去掉 LLM 常带的 ``` 围栏与首尾空白（语言标识任意：mermaid/markdown/无）。

    整段被围栏包裹时只剥最外层——需求逻辑文档正文内部可能有 ```python 代码块，
    不能用非贪婪匹配在第一个内部围栏处截断。带前导说明的输出（"时序图如下：\\n```…"）
    则退回"取第一个围栏内容"，避免时序图因说明文字被判非法。
    """
    if not text:
        return ""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]  # 去首行 ```lang
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    match = FENCE_RE.search(stripped)
    return (match.group(1) if match else stripped).strip()


def _meaningful_lines(text: str) -> list[str]:
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("%%")
    ]


def split_arrow(line: str) -> tuple[str, str, str] | None:
    """箭头行拆分：返回 (发送方, 接收方, 消息)；不是箭头行返回 None。"""
    match = ARROW_TOKEN_RE.search(line)
    if match is None:
        return None
    left = line[: match.start()].strip()
    rest = line[match.end():]
    if ":" not in rest:
        return None
    right, message = rest.split(":", 1)
    # 激活标记 +/- 紧跟箭头，不属于参与者名
    right = right.strip().lstrip("+-").strip()
    if not left or not right:
        return None
    return left, right, message.strip()


def validate_sequence(text: str) -> tuple[bool, str]:
    """时序图校验：(是否合法, 失败原因)。原因用于重试提示词与日志。"""
    body = strip_fence(text)
    if not body:
        return False, "输出为空"
    lines = _meaningful_lines(body)
    if not lines:
        return False, "图内容为空"
    if not lines[0].strip().lower().startswith("sequencediagram"):
        return False, f"首行不是 sequenceDiagram 声明（实际：{lines[0].strip()[:40]}）"

    arrows: list[tuple[str, str, str]] = []
    for line in lines[1:]:
        stripped = line.strip()
        lowered = stripped.lower()
        if PARTICIPANT_RE.match(stripped):
            continue
        if lowered.startswith(("participant", "actor")):
            return False, f"参与者行格式非法：{stripped[:60]}"
        parsed = split_arrow(stripped)
        if parsed is not None:
            arrows.append(parsed)
            continue
        if lowered.split(" ", 1)[0].rstrip(":") in SEQ_KEYWORDS:
            continue
        return False, f"无法识别的行（疑似混入说明文字）：{stripped[:60]}"

    if not arrows:
        return False, "没有任何消息箭头行"
    actors = {a for a, _, _ in arrows} | {b for _, b, _ in arrows}
    if len(actors) < 2:
        return False, "参与者不足 2 个，时序图无意义"
    return True, ""


def validate_mindmap(text: str) -> tuple[bool, str]:
    """思维导图校验（程序化生成，作为自检兜底）。"""
    body = strip_fence(text)
    lines = _meaningful_lines(body)
    if not lines:
        return False, "图内容为空"
    if lines[0].strip().lower() != "mindmap":
        return False, "首行不是 mindmap 声明"
    if len(lines) < 2:
        return False, "mindmap 没有任何节点"
    if not lines[1].startswith((" ", "\t")):
        return False, "根节点缺少缩进"
    return True, ""
