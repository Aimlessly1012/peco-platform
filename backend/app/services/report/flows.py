"""业务流程图（M6 B5）：从 L4 核心业务流 + L3 关键流程生成 flowchart。

需求方向而非代码方向——节点是业务步骤（用户动作/系统行为），不是文件与函数；
代码级的调用链由聊天的影响面分析与时序图承担。

单次 LLM 调用产出多张图，逐张校验：整体不合格重试 1 次，仍不合格则整体降级为
业务流原文（fallback_text）。不做缓存——输入依赖每次重算的 L4，一次调用的成本可忽略。
"""
import logging
import re

from app.services.report.graph_reader import ProjectTree
from app.services.report.mermaid_check import (
    MAX_FLOW_NODES,
    strip_fence,
    validate_flowchart,
)

logger = logging.getLogger(__name__)

MAX_FLOWS = 4
MAX_TITLE_CHARS = 12
FLOW_SECTION_RE = re.compile(r"^##\s*(?P<title>.+?)\s*$", re.M)
MERMAID_BLOCK_RE = re.compile(r"```[ \t]*[a-zA-Z]*[ \t]*\n(.*?)```", re.S)

# L4 / L3 里的锚点小节名（summarizer 的固定输出格式）
PROJECT_FLOW_HEADING = "核心业务流"
MODULE_FLOW_HEADING = "关键流程"
FEATURE_KINDS = ("page", "api")


def _section_lines(text: str, heading: str) -> list[str]:
    """从"标题：内容"式摘要里抠出某一节的正文行。"""
    lines = (text or "").splitlines()
    collected: list[str] = []
    capturing = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(heading):
            capturing = True
            rest = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            if rest and rest != line:
                collected.append(rest)
            continue
        if capturing:
            # 遇到下一个"某某："小节就停
            if re.match(r"^[一-龥A-Za-z]{2,8}[：:]", line):
                break
            collected.append(line.lstrip("-–—• 　"))
    return [line for line in collected if line]


def project_flow_lines(tree: ProjectTree) -> list[str]:
    """L4 的「核心业务流」条目；取不到就退回整段总览。"""
    lines = _section_lines(tree.summary, PROJECT_FLOW_HEADING)
    if lines:
        return lines
    summary = (tree.summary or "").strip()
    return [summary] if summary else []


def module_flow_lines(tree: ProjectTree, max_modules: int = 12) -> list[str]:
    """各功能域的「关键流程」，作为业务流的细节支撑。"""
    blocks: list[str] = []
    modules = [m for m in tree.modules if m.kind in FEATURE_KINDS]
    modules.sort(key=lambda m: (-len(m.files), m.name))
    for module in modules[:max_modules]:
        steps = _section_lines(module.summary, MODULE_FLOW_HEADING)
        if not steps:
            continue
        joined = "；".join(steps[:4])
        blocks.append(f"- {module.name}：{joined}")
    return blocks


def parse_business_flows(raw: str) -> list[dict]:
    """解析「## 标题 + mermaid 块」的多图输出。"""
    text = (raw or "").strip()
    if not text:
        return []
    flows: list[dict] = []
    matches = list(FLOW_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = MERMAID_BLOCK_RE.search(text[start:end])
        if block is None:
            continue
        title = match.group("title").strip().strip("#").strip()
        flows.append(
            {"title": title[:MAX_TITLE_CHARS] or f"业务流 {index + 1}",
             "mermaid": block.group(1).strip()}
        )
    if not flows:
        # 没有标题行但只给了一张图时也认（模型偶尔省略标题）
        block = MERMAID_BLOCK_RE.search(text)
        body = strip_fence(block.group(0)) if block else text
        if body.strip().lower().startswith(("flowchart", "graph")):
            flows.append({"title": "核心业务流", "mermaid": body.strip()})
    return flows[:MAX_FLOWS]


def validate_flows(flows: list[dict]) -> tuple[list[dict], str]:
    """逐张校验，返回 (合格的图, 失败原因)。一张都不合格才算整体失败。"""
    valid: list[dict] = []
    reasons: list[str] = []
    for flow in flows:
        ok, reason = validate_flowchart(flow["mermaid"], max_nodes=MAX_FLOW_NODES)
        if ok:
            valid.append(flow)
        else:
            reasons.append(f"《{flow['title']}》{reason}")
    return valid, "；".join(reasons[:3])


def fallback_flows(tree: ProjectTree) -> list[dict]:
    """降级：把业务流原文按条存成文字版，前端显示 fallback_text。"""
    lines = project_flow_lines(tree)
    if not lines:
        return []
    return [
        {
            "title": "核心业务流",
            "mermaid": "",
            "fallback_text": "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)),
        }
    ]


async def generate_business_flows(tree: ProjectTree, llm) -> tuple[list[dict], dict]:
    """返回 (business_flows, stats)。失败重试 1 次后整体降级为业务流原文。"""
    flow_lines = project_flow_lines(tree)
    stats = {"business_flows_ok": 0, "business_flows_fallback": 0}
    if not flow_lines:
        logger.info("项目总览中没有核心业务流，跳过业务流程图")
        return [], stats

    module_flows = module_flow_lines(tree)
    reason = ""
    for attempt in range(2):
        try:
            raw = await llm.generate_business_flows(
                "\n".join(f"- {line}" for line in flow_lines),
                "\n".join(module_flows),
                max_flows=MAX_FLOWS,
                max_nodes=MAX_FLOW_NODES,
                retry_reason=reason,
            )
        except Exception as e:  # noqa: BLE001 — 报告不阻塞索引
            logger.warning("业务流程图调用异常（%s: %s）", type(e).__name__, e)
            raw = None
        if not raw:
            reason = "模型未返回内容"
            continue
        valid, reason = validate_flows(parse_business_flows(raw))
        if valid:
            for flow in valid:
                flow.setdefault("fallback_text", "")
            stats["business_flows_ok"] = len(valid)
            return valid, stats
        logger.warning("业务流程图校验失败（第 %d 次）：%s", attempt + 1, reason or "无有效图")

    logger.warning("业务流程图两次均失败，降级为业务流文字版")
    degraded = fallback_flows(tree)
    stats["business_flows_fallback"] = len(degraded)
    return degraded, stats
