"""模块数据流图单测（M5 B3）：聚合边 → flowchart 模板、弱边省略与上限截断。"""
import pytest

from app.services.report.dataflow import (
    MAX_EDGES,
    build_dataflow,
    select_edges,
)
from app.services.report.graph_reader import ModuleEdge
from tests.test_report import make_tree


def edge(src: str, dst: str, relation: str = "calls_api", count: int = 3) -> ModuleEdge:
    src_kind, src_name = src.split(":", 1)
    dst_kind, dst_name = dst.split(":", 1)
    return ModuleEdge(
        src_key=src, src_name=src_name, src_kind=src_kind,
        dst_key=dst, dst_name=dst_name, dst_kind=dst_kind,
        relation=relation, count=count,
    )


def edge_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if "|" in ln]


def test_dataflow_renders_nodes_and_labelled_edges():
    tree = make_tree()
    edges = [
        edge("page:orders", "api:orders", "calls_api", 5),
        edge("api:orders", "shared:shared", "imports", 3),
    ]

    out = build_dataflow(tree, edges)

    assert out.startswith("flowchart LR")
    assert '["[页面] orders"]' in out
    assert '["[接口] orders"]' in out
    # CALLS_API 实线、IMPORTS 虚线，边标注条数
    assert any('-->|"x5"|' in ln for ln in edge_lines(out))
    assert any('-.->|"x3"|' in ln for ln in edge_lines(out))


def test_dataflow_only_contains_graph_modules():
    """M5 spec 场景: 每条边都对应真实聚合关系，不含图中不存在的模块。"""
    tree = make_tree()
    out = build_dataflow(tree, [edge("page:orders", "api:orders")])

    labels = [ln.split('["', 1)[1].rsplit('"]', 1)[0] for ln in out.splitlines() if '["' in ln]
    real_names = {m.name for m in tree.modules}
    for label in labels:
        assert label.split("] ", 1)[-1] in real_names


def test_dataflow_applies_kind_styles():
    tree = make_tree()
    out = build_dataflow(tree, [edge("page:orders", "api:orders")])

    assert "classDef api" in out
    assert "classDef page" in out
    assert out.count("class n") == 2


def test_dataflow_empty_when_no_cross_module_relation():
    out = build_dataflow(make_tree(), [])
    assert out.startswith("flowchart LR")
    assert "暂无跨模块调用或依赖" in out


def test_select_edges_keeps_everything_under_limit():
    """小项目的边普遍只有 1 条——无差别过滤弱边会得到空图。"""
    edges = [edge(f"api:m{i}", f"api:m{i + 1}", count=1) for i in range(5)]
    selected, omitted = select_edges(edges)

    assert len(selected) == 5
    assert omitted == 0


def test_select_edges_drops_weak_when_over_limit():
    """超限时才启用弱边过滤（<2 省略）。"""
    strong = [edge(f"api:s{i}", f"api:t{i}", count=5) for i in range(40)]
    weak = [edge(f"api:w{i}", f"api:v{i}", count=1) for i in range(40)]
    selected, omitted = select_edges(strong + weak)

    assert len(selected) == 40
    assert all(e.count >= 2 for e in selected)
    assert omitted == 40


def test_select_edges_truncates_by_weight():
    edges = [edge(f"api:s{i}", f"api:t{i}", count=i + 2) for i in range(100)]
    selected, omitted = select_edges(edges)

    assert len(selected) == MAX_EDGES
    assert omitted == 100 - MAX_EDGES
    # 按权重降序截断：保留的是最强的那批
    assert min(e.count for e in selected) > max(
        e.count for e in edges if e not in selected
    )


def test_dataflow_marks_omitted_edges():
    edges = [edge(f"api:s{i}", f"api:t{i}", count=i + 2) for i in range(100)]
    out = build_dataflow(make_tree(), edges)

    assert "另有 40 条弱关联未显示" in out


@pytest.mark.parametrize("relation,arrow", [("calls_api", "-->"), ("imports", "-.->")])
def test_relation_arrow_mapping(relation, arrow):
    out = build_dataflow(make_tree(), [edge("page:orders", "api:orders", relation, 2)])
    assert any(arrow in ln for ln in edge_lines(out))


def test_dataflow_escapes_module_names():
    tree = make_tree()
    tricky = edge('page:a"b', "api:orders")
    out = build_dataflow(tree, [tricky])

    for line in out.splitlines():
        if '["' in line:
            inner = line.split('["', 1)[1].rsplit('"]', 1)[0]
            assert '"' not in inner
