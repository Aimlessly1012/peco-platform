"""M3 报告与 MCP 数据底座集成测试（需要 Neo4j：docker compose up -d neo4j）。

单测里图读取全是打桩，这里用 mini_repo 真实写图后回读，验证：
- graph_reader 读到的属性名/层级与 graph_writer 写入的一致（半成品最容易错的地方）
- spec 场景「思维导图与图数据一致」：mindmap 中不出现图里没有的名称
- MCP 工具依赖的 read_file_detail / read_impact / read_project_stats 语义正确
"""
import uuid

import pytest

from app.graph.client import close_driver, delete_project_graph, ensure_vector_index
from app.services.report.builder import select_core_modules
from app.services.report.graph_reader import (
    read_file_detail,
    read_graph_edges,
    read_impact,
    read_project_stats,
    read_project_tree,
    resolve_symbol_files,
)
from app.services.report.mermaid_check import validate_mindmap
from app.services.report.mindmap import build_mindmap
from app.services.report.service import build_report
from tests.test_pipeline_integration import _index_fixture
from tests.test_report import GOOD_SEQ, FakeLLM

pytestmark = pytest.mark.integration


@pytest.fixture
async def indexed_project(fake_embedder, fake_summarizer):
    await ensure_vector_index()
    pid = f"test-{uuid.uuid4().hex[:8]}"
    files, chunks, modules, api_edges = await _index_fixture(pid, fake_embedder, fake_summarizer)
    yield pid, files, modules
    await delete_project_graph(pid)
    await close_driver()


async def test_read_project_tree_matches_written_graph(indexed_project):
    pid, files, modules = indexed_project
    tree = await read_project_tree(pid)

    assert tree.project_id == pid
    assert tree.name == "mini-shop"          # Project.display_name
    assert tree.summary                       # L4 总览
    assert {m.key for m in tree.modules} == {m.key for m in modules}

    for mod in tree.modules:
        written = next(m for m in modules if m.key == mod.key)
        assert mod.name == written.name
        assert mod.kind == written.kind
        assert mod.route_prefix == written.route_prefix
        assert mod.summary == written.summary

    # 文件层级：树里的文件集合 = 各文件归属声明的并集，且带 L2 摘要
    tree_pairs = {(m.key, f.path) for m in tree.modules for f in m.files}
    written_pairs = {(key, f.path) for f in files for key in f.modules}
    assert tree_pairs == written_pairs
    assert all(f.summary for m in tree.modules for f in m.files)
    assert all(f.language for m in tree.modules for f in m.files)


async def test_mindmap_only_contains_graph_names(indexed_project):
    """spec 场景: 思维导图与图数据一致——不含图中不存在的名称。"""
    pid, files, modules = indexed_project
    tree = await read_project_tree(pid)
    out = build_mindmap(tree)

    assert validate_mindmap(out) == (True, "")
    real_paths = {f.path for f in files}
    real_modules = {m.name for m in modules}
    for line in out.splitlines():
        if '["' not in line:
            continue
        text = line.split('["', 1)[1].rsplit('"]', 1)[0]
        if text.startswith("["):          # 模块行：[接口] orders /api/orders
            name = text.split("] ", 1)[1].split(" ")[0]
            assert name in real_modules, f"图中不存在的模块：{name}"
        elif not text.startswith("…"):    # 文件行
            assert text in real_paths, f"图中不存在的文件：{text}"


async def test_read_graph_edges(indexed_project):
    pid, _, _ = indexed_project
    edges = await read_graph_edges(pid)

    assert edges.api_edges, "mini_repo 有前端 → 后端 handler 调用"
    api = edges.api_edges[0]
    assert api.src_file and api.dst_file and api.dst_symbol
    assert api.src_start > 0

    imports = {(e.src, e.dst) for e in edges.import_edges}
    assert ("backend/routers/orders.py", "backend/services/order_service.py") in imports


async def test_read_file_detail(indexed_project):
    pid, _, _ = indexed_project
    detail = await read_file_detail(pid, "backend/routers/orders.py")

    assert detail is not None
    assert detail["language"] == "python"
    assert detail["summary"]
    symbols = {s["name"] for s in detail["symbols"]}
    assert "create_order" in symbols
    assert all("-" in s["lines"] for s in detail["symbols"])
    assert "backend/services/order_service.py" in detail["imports"]
    assert detail["modules"]

    assert await read_file_detail(pid, "no/such/file.py") is None


async def test_read_impact_one_hop(indexed_project):
    """spec 场景: 对后端 handler 文件做影响面分析。"""
    pid, _, _ = indexed_project
    impact = await read_impact(pid, "backend/routers/orders.py")

    callers = {c["file_path"] for c in impact["api_callers"]}
    assert callers, "应能反查到经 CALLS_API 调用它的前端代码块"
    assert impact["modules_affected"]
    assert all(m["name"] for m in impact["modules_affected"])


async def test_resolve_symbol_and_stats(indexed_project):
    pid, files, modules = indexed_project

    assert "backend/routers/orders.py" in await resolve_symbol_files(pid, "create_order")
    assert await resolve_symbol_files(pid, "不存在的符号") == []

    stats = await read_project_stats(pid)
    assert stats["modules_count"] == len(modules)
    assert "python" in stats["languages"]


async def test_project_isolation(indexed_project, fake_embedder, fake_summarizer):
    """两个项目同时在库里时，读取只返回自己项目的数据。"""
    pid, _, _ = indexed_project
    other = f"test-{uuid.uuid4().hex[:8]}"
    try:
        await _index_fixture(other, fake_embedder, fake_summarizer)
        tree = await read_project_tree(pid)
        other_tree = await read_project_tree(other)

        assert tree.project_id != other_tree.project_id
        # 文件数相同（同一 fixture），但节点归属互不串台
        assert tree.file_count == other_tree.file_count > 0
        impact = await read_impact(pid, "backend/routers/orders.py")
        assert impact["api_callers"]  # 仍能查到，且不受另一项目影响
    finally:
        await delete_project_graph(other)


async def test_build_report_end_to_end(indexed_project):
    """读真实图 → 三件套：导图程序化必成，文档与时序图走 mock LLM。"""
    pid, _, _ = indexed_project
    tree = await read_project_tree(pid)
    core = select_core_modules(tree)
    llm = FakeLLM(doc_returns="# mini-shop 需求逻辑文档\n正文", seq_returns=[GOOD_SEQ] * len(core))

    result = await build_report(pid, llm=llm)

    assert result.mindmap_mermaid.startswith("mindmap")
    assert result.doc_markdown.startswith("# mini-shop")
    assert result.stats["report_modules"] == len(tree.modules)
    assert result.stats["sequences_ok"] == len(core)
    assert result.stats["doc_fallback"] is False
    for seq in result.sequences:
        assert seq["module_key"] in {m.key for m in tree.modules}
        assert seq["mermaid"].startswith("sequenceDiagram")
