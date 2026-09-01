"""顶层思维导图程序化生成（M5 D1）：Project→Module 两层。

零 LLM、零幻觉：输出中出现的每个模块名都来自图数据，必定成功。

M5 起不再画文件层——49 模块的项目会产出 1739 个节点，浏览器渲染出来是一团糊。
模块子导图（Module→Files）改由前端按需拼装：`GET /projects/{id}/modules` 已返回
全量模块与文件数据，点开哪个模块拼哪个，零后端存储、零生成时间。
"""
import re

from app.services.report.graph_reader import ProjectTree

INDENT = "  "
MAX_TEXT = 80

KIND_LABEL = {
    "api": "接口",
    "page": "页面",
    "dir": "目录",
    "shared": "共享",
}


def escape_node_text(text: str) -> str:
    """mermaid 节点文本转义：折行压平、双引号/反引号替换（节点一律用 id["文本"] 形式包裹）。

    引号包裹后除 `"` 外的字符都安全；反引号会触发 markdown 字符串模式，一并替换。
    """
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    cleaned = cleaned.replace('"', "'").replace("`", "'")
    if len(cleaned) > MAX_TEXT:
        cleaned = cleaned[: MAX_TEXT - 1] + "…"
    return cleaned or "(未命名)"


def _module_label(kind: str, name: str, route_prefix: str, file_count: int) -> str:
    label = KIND_LABEL.get(kind, kind or "模块")
    text = f"[{label}] {name}"
    if route_prefix:
        text += f" {route_prefix}"
    return f"{text} · {file_count} 文件"


def sort_modules(tree: ProjectTree):
    """接口/页面在前，同 kind 内文件多的靠前——顶图第一屏就是主干。"""
    kind_order = {"api": 0, "page": 1, "dir": 2, "shared": 3}
    return sorted(
        tree.modules,
        key=lambda m: (kind_order.get(m.kind, 9), -len(m.files), m.name),
    )


def build_mindmap(tree: ProjectTree) -> str:
    """顶层导图：根=项目，一级=功能模块（带 kind、路由前缀与文件数）。节点数 = 模块数 + 1。"""
    root_text = escape_node_text(tree.name or tree.project_id)
    lines = ["mindmap", f'{INDENT}root(("{root_text}"))']

    if not tree.modules:
        lines.append(f'{INDENT * 2}empty["（图中暂无模块数据）"]')
        return "\n".join(lines)

    for i, mod in enumerate(sort_modules(tree)):
        label = escape_node_text(
            _module_label(mod.kind, mod.name, mod.route_prefix, len(mod.files))
        )
        lines.append(f'{INDENT * 2}m{i}["{label}"]')
    return "\n".join(lines)
