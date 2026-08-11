"""思维导图程序化生成（设计 D1）：Cypher 读出的 Project→Module→File 树 → mermaid mindmap。

零 LLM、零幻觉：输出中出现的每个模块/文件名都来自图数据，必定成功。
"""
import re

from app.services.report.graph_reader import ProjectTree

INDENT = "  "
MAX_FILES_PER_MODULE = 12
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


def _module_label(kind: str, name: str, route_prefix: str) -> str:
    label = KIND_LABEL.get(kind, kind or "模块")
    text = f"[{label}] {name}"
    if route_prefix:
        text += f" {route_prefix}"
    return text


def build_mindmap(tree: ProjectTree, max_files: int = MAX_FILES_PER_MODULE) -> str:
    """生成 mermaid mindmap 源码：根=项目，一级=功能模块（带 kind/路由前缀），二级=文件。"""
    root_text = escape_node_text(tree.name or tree.project_id)
    lines = ["mindmap", f'{INDENT}root(("{root_text}"))']

    if not tree.modules:
        lines.append(f'{INDENT * 2}empty["（图中暂无模块数据）"]')
        return "\n".join(lines)

    # 模块排序：接口/页面在前，其余按 kind、名称；同 kind 内文件多的靠前
    kind_order = {"api": 0, "page": 1, "dir": 2, "shared": 3}
    modules = sorted(
        tree.modules,
        key=lambda m: (kind_order.get(m.kind, 9), -len(m.files), m.name),
    )
    for i, mod in enumerate(modules):
        label = escape_node_text(_module_label(mod.kind, mod.name, mod.route_prefix))
        lines.append(f'{INDENT * 2}m{i}["{label}"]')
        for j, f in enumerate(mod.files[:max_files]):
            lines.append(f'{INDENT * 3}m{i}f{j}["{escape_node_text(f.path)}"]')
        remaining = len(mod.files) - max_files
        if remaining > 0:
            lines.append(f'{INDENT * 3}m{i}more["… 其余 {remaining} 个文件"]')
    return "\n".join(lines)
