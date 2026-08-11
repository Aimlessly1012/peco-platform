"""管道集成测试（需要 Neo4j：docker compose up neo4j -d）。

覆盖 spec 场景：
- 写入后图结构可查（File/Chunk 节点数与 stats 一致、DEFINES 可回溯）
- 全量重建后无残留
- 检索冒烟：3 个局部问题命中预期文件（跨项目隔离）
"""
import uuid
from pathlib import Path

import pytest

from app.graph.client import (
    close_driver,
    delete_project_graph,
    ensure_vector_index,
    get_driver,
)
from app.services.ingest.pipeline import build_embed_text
from app.services.ingest.graph_writer import FileInfo, write_project_graph
from app.services.ingest.pipeline import _parse_all
from app.services.ingest.walker import walk_repo
from app.services.retrieval.service import search_chunks

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "mini_repo"

pytestmark = pytest.mark.integration


async def _index_fixture(project_id: str, fake_embedder) -> tuple[list, list]:
    """跑 parse→embed→graph 段（git 阶段由手动验收覆盖）。"""
    walk = walk_repo(FIXTURE_REPO)
    files, chunks, parse_failed = _parse_all(FIXTURE_REPO, walk.files)
    assert parse_failed == 0

    context_texts = {c.content_hash: build_embed_text(c) for c in chunks}
    unique = {c.content_hash: c for c in chunks}
    vectors = await fake_embedder.embed_texts(
        [context_texts[h] for h in unique]
    )
    embeddings = dict(zip(unique.keys(), vectors))

    await write_project_graph(
        project_id, "mini-shop", "file://fixture", files, chunks, context_texts, embeddings
    )
    return files, chunks


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


async def test_graph_write_and_counts(neo4j_ready, fake_embedder):
    pid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        files, chunks = await _index_fixture(pid, fake_embedder)

        file_count = await _count(
            "MATCH (f:File {project_id: $pid}) RETURN count(f) AS n", pid=pid
        )
        chunk_count = await _count(
            "MATCH (c:Chunk {project_id: $pid}) RETURN count(c) AS n", pid=pid
        )
        defines_count = await _count(
            "MATCH (:File {project_id: $pid})-[r:DEFINES]->(:Chunk) RETURN count(r) AS n",
            pid=pid,
        )
        assert file_count == len(files) == 9  # fixture: 5 py + 3 tsx + 1 ts
        assert chunk_count == len(chunks)
        assert defines_count == len(chunks)  # 每个 Chunk 经 DEFINES 可回溯

        # 全量重建后无残留
        await delete_project_graph(pid)
        remaining = await _count(
            "MATCH (n {project_id: $pid}) RETURN count(n) AS n", pid=pid
        )
        assert remaining == 0
    finally:
        await delete_project_graph(pid)


async def test_retrieval_smoke(neo4j_ready, fake_embedder):
    pid = f"test-{uuid.uuid4().hex[:8]}"
    pid_other = f"test-{uuid.uuid4().hex[:8]}"
    try:
        await _index_fixture(pid, fake_embedder)
        await _index_fixture(pid_other, fake_embedder)  # 干扰项目，验证隔离

        cases = [
            ("create_order 创建订单的接口在哪", "backend/routers/orders.py"),
            ("OrderCard 组件渲染什么", "frontend/components/OrderCard.tsx"),
            ("cancel 取消订单的业务逻辑", "backend/services/order_service.py"),
        ]
        for question, expected_file in cases:
            results = await search_chunks(pid, question, top_k=5)
            assert results, f"无检索结果: {question}"
            hit_files = [r.file_path for r in results]
            assert expected_file in hit_files, (
                f"问题「{question}」未命中 {expected_file}，实际: {hit_files}"
            )
            # 跨项目隔离：结果只属于当前项目
            assert all(r.node_id.startswith(pid) for r in results)
    finally:
        await delete_project_graph(pid)
        await delete_project_graph(pid_other)
