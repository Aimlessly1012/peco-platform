"""管道集成测试（M2，需要 Neo4j：docker compose up neo4j -d）。

覆盖 spec 场景：
- 写入后图结构可查：Module/File/Chunk 节点、DEFINES→CONTAINS→HAS_MODULE 回溯链
- CALLS_API / IMPORTS 边连通
- 全量重建后无残留
- 检索冒烟：局部问题命中预期文件；全局问题命中摘要层（跨项目隔离）
"""
import uuid

import pytest

from app.graph.client import (
    close_driver,
    delete_project_graph,
    ensure_vector_index,
    get_driver,
)
from app.services.retrieval.service import search_layered
# M17 3.2：建图流程提升为共享 helper，评测 harness 与本文件共用同一套
from tests.helpers.fixture_graph import index_fixture_repo

pytestmark = pytest.mark.integration


@pytest.fixture
async def neo4j_ready():
    await ensure_vector_index()
    yield
    await close_driver()


async def _count(cypher: str, **params) -> int:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **params)
        record = await result.single()
        return record["n"]


async def test_graph_write_m2_schema(neo4j_ready, fake_embedder, fake_summarizer):
    pid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        files, chunks, modules, api_edges = await index_fixture_repo(pid, fake_embedder, fake_summarizer)

        module_count = await _count(
            "MATCH (m:Module {project_id: $pid}) RETURN count(m) AS n", pid=pid
        )
        assert module_count == len(modules) >= 3  # page/api 模块 + shared

        # spec: DEFINES→CONTAINS→HAS_MODULE 回溯链
        traceable = await _count(
            "MATCH (p:Project {project_id: $pid})-[:HAS_MODULE]->(:Module)"
            "-[:CONTAINS]->(:File)-[:DEFINES]->(c:Chunk) RETURN count(DISTINCT c) AS n",
            pid=pid,
        )
        assert traceable == len(chunks)

        # spec: CALLS_API 边连通前后端
        api_edge_count = await _count(
            "MATCH (:Chunk {project_id: $pid})-[r:CALLS_API]->(:Chunk) RETURN count(r) AS n",
            pid=pid,
        )
        assert api_edge_count >= 2  # apiGet + apiPost → list_orders / create_order

        # spec: IMPORTS 边
        imports_count = await _count(
            "MATCH (:File {project_id: $pid})-[r:IMPORTS]->(:File) RETURN count(r) AS n",
            pid=pid,
        )
        assert imports_count >= 3

        # 全量重建后无残留
        await delete_project_graph(pid)
        remaining = await _count(
            "MATCH (n {project_id: $pid}) RETURN count(n) AS n", pid=pid
        )
        assert remaining == 0
    finally:
        await delete_project_graph(pid)


async def test_layered_retrieval_smoke(neo4j_ready, fake_embedder, fake_summarizer):
    pid = f"test-{uuid.uuid4().hex[:8]}"
    pid_other = f"test-{uuid.uuid4().hex[:8]}"
    try:
        await index_fixture_repo(pid, fake_embedder, fake_summarizer)
        await index_fixture_repo(pid_other, fake_embedder, fake_summarizer)

        # 局部问题命中预期代码块
        results = await search_layered(pid, "create_order 创建订单的接口在哪", "local", top_k=6)
        assert results
        hit_files = [r.file_path for r in results if r.kind == "chunk"]
        assert "backend/routers/orders.py" in hit_files
        assert all(r.node_id.startswith(pid) for r in results)  # 跨项目隔离

        # spec: 全局问题命中摘要层
        results = await search_layered(pid, "orders 模块 业务流程 架构", "global", top_k=8)
        kinds = {r.kind for r in results}
        assert "module_summary" in kinds or "file_summary" in kinds

        # spec: 前端块经 CALLS_API 带出后端对端
        results = await search_layered(pid, "OrdersPage 订单页面 apiGet", "local", top_k=5)
        via_edges = {r.via_edge for r in results}
        assert "calls_api" in via_edges or "defines_file" in via_edges
    finally:
        await delete_project_graph(pid)
        await delete_project_graph(pid_other)
