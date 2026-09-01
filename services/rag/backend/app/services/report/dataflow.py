"""模块数据流图程序化生成（M5 D2）：模块间聚合边 → mermaid flowchart。

与顶层导图同属"必然成功"档：零 LLM、零幻觉，图里每条边都来自 Neo4j 的真实聚合，
因此不设 LLM 类降级——这里出错就是管道缺陷，要修不要兜。
"""
from app.services.report.graph_reader import ModuleEdge, ProjectTree
from app.services.report.mindmap import KIND_LABEL, escape_node_text

MAX_EDGES = 60
WEAK_EDGE_THRESHOLD = 2

# 按 kind 分色，与顶层导图的语义分类保持一致
KIND_STYLE = {
    "api": "fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a",
    "page": "fill:#dcfce7,stroke:#22c55e,color:#14532d",
    "dir": "fill:#fef3c7,stroke:#f59e0b,color:#78350f",
    "shared": "fill:#f1f5f9,stroke:#94a3b8,color:#334155",
}
ARROW = {"calls_api": "-->", "imports": "-.->"}  # 实线 = HTTP 调用，虚线 = 代码依赖


def select_edges(
    edges: list[ModuleEdge],
    max_edges: int = MAX_EDGES,
    weak_threshold: int = WEAK_EDGE_THRESHOLD,
) -> tuple[list[ModuleEdge], int]:
    """按权重挑选要画的边，返回 (入选边, 被省略的边数)。

    弱边过滤只在边数超限时启用——小项目的边普遍只有 1，无差别过滤会得到一张空图，
    而"防爆炸"针对的本来就是强耦合的大项目。
    """
    ordered = sorted(
        edges, key=lambda e: (-e.count, e.src_name, e.dst_name, e.relation)
    )
    if len(ordered) <= max_edges:
        return ordered, 0

    strong = [e for e in ordered if e.count >= weak_threshold]
    if len(strong) <= max_edges:
        return strong, len(ordered) - len(strong)
    return strong[:max_edges], len(ordered) - max_edges


def build_dataflow(tree: ProjectTree, edges: list[ModuleEdge]) -> str:
    """生成 mermaid flowchart LR：节点=参与关系的模块，边=聚合关系（标注条数）。"""
    selected, omitted = select_edges(edges)
    if not selected:
        return (
            "flowchart LR\n"
            '    empty["（模块之间暂无跨模块调用或依赖）"]'
        )

    kind_by_key = {m.key: m.kind for m in tree.modules}
    name_by_key = {m.key: m.name for m in tree.modules}

    # 节点只收参与边的模块：数据流图表达的是"流"，孤立模块在顶层导图里已经能看到
    node_ids: dict[str, str] = {}
    for edge in selected:
        for key in (edge.src_key, edge.dst_key):
            if key not in node_ids:
                node_ids[key] = f"n{len(node_ids)}"

    lines = ["flowchart LR"]
    for key, node_id in node_ids.items():
        kind = kind_by_key.get(key, key.split(":", 1)[0])
        name = name_by_key.get(key, key.split(":", 1)[-1])
        label = escape_node_text(f"[{KIND_LABEL.get(kind, kind)}] {name}")
        lines.append(f'    {node_id}["{label}"]')

    for edge in selected:
        arrow = ARROW.get(edge.relation, "-->")
        lines.append(
            f'    {node_ids[edge.src_key]} {arrow}|"x{edge.count}"| '
            f"{node_ids[edge.dst_key]}"
        )

    used_kinds = {kind_by_key.get(key, key.split(":", 1)[0]) for key in node_ids}
    for kind in sorted(used_kinds):
        style = KIND_STYLE.get(kind)
        if style:
            lines.append(f"    classDef {kind} {style}")
    for key, node_id in node_ids.items():
        kind = kind_by_key.get(key, key.split(":", 1)[0])
        if kind in KIND_STYLE:
            lines.append(f"    class {node_id} {kind}")

    if omitted:
        lines.append(f'    note["… 另有 {omitted} 条弱关联未显示"]')
    return "\n".join(lines)
