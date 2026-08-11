"""管道集成测试（M2，需要 Neo4j：docker compose up neo4j -d）。

覆盖 spec 场景：
- 写入后图结构可查：Module/File/Chunk 节点、DEFINES→CONTAINS→HAS_MODULE 回溯链
- CALLS_API / IMPORTS 边连通
- 全量重建后无残留
- 检索冒烟：局部问题命中预期文件；全局问题命中摘要层（跨项目隔离）
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
from app.services.ingest.api_matcher import extract_api_edges
from app.services.ingest.graph_writer import ModuleInfo, write_project_graph
from app.services.ingest.module_mapper import (
    assign_files,
    ensure_shared_module,
    module_key,
)
from app.services.ingest.pipeline import _hash16, _parse_all, build_embed_text
from app.services.ingest.router_parser import parse_routes
from app.services.ingest.summarizer import module_agg_hash
from app.services.ingest.walker import walk_repo
from app.services.retrieval.service import search_layered

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "mini_repo"

pytestmark = pytest.mark.integration


async def _index_fixture(project_id: str, fake_embedder, fake_summarizer):
    """跑 M2 parse→summarize→embed→graph 段（git 阶段由手动验收覆盖）。"""
    walk = walk_repo(FIXTURE_REPO)
    files, chunks, imports, heads, parse_failed = _parse_all(FIXTURE_REPO, walk.files)
    assert parse_failed == 0

    file_paths = [f.path for f in files]
    repo_files = {f.path: (FIXTURE_REPO / f.path).read_text(encoding="utf-8") for f in files}
    for extra in FIXTURE_REPO.rglob("package.json"):
        repo_files[str(extra.relative_to(FIXTURE_REPO))] = extra.read_text(encoding="utf-8")

    module_map = parse_routes(file_paths, repo_files)
    assignment = assign_files(file_paths, module_map, imports)
    ensure_shared_module(module_map, assignment)
    for f in files:
        f.modules = assignment.get(f.path, ["shared"])
        f.imports = sorted(imports.get(f.path, set()))

    chunks_by_key = {(c.file_path, c.symbol): c for c in chunks}
    frontend_chunks = [c for c in chunks if c.language != "python"]
    api_edges, _ = extract_api_edges(frontend_chunks, module_map.backend_routes, chunks_by_key)

    # 摘要（mock）
    files_by_path = {f.path: f for f in files}
    chunks_by_file = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_path, []).append(c)
    for f in files:
        f.summary = await fake_summarizer.summarize_file(
            f.path, imports.get(f.path, set()), chunks_by_file.get(f.path, []), ""
        )
    module_summaries = {}
    for m in module_map.modules:
        module_summaries[module_key(m)] = await fake_summarizer.summarize_module(
            m.name, m.kind, m.route_prefix, m.entry_files, {}
        )
    project_summary = await fake_summarizer.summarize_project("", module_map, module_summaries)

    # 嵌入（fake，embed_key 缓存键）
    embed_texts, embed_keys, embeddings = {}, {}, {}
    for c in chunks:
        f = files_by_path.get(c.file_path)
        text = build_embed_text(c, "mini-shop", f.modules if f else ["shared"], "", f.summary if f else "")
        embed_texts[c.content_hash] = text
        embed_keys[c.content_hash] = _hash16(text)
    unique = list({c.content_hash: c for c in chunks})
    vectors = await fake_embedder.embed_texts([embed_texts[h] for h in unique])
    embeddings = dict(zip(unique, vectors))

    for f in files:
        f.summary_embedding = (await fake_embedder.embed_texts([f.summary]))[0]
    modules_info = [
        ModuleInfo(
            name=m.name, key=module_key(m), kind=m.kind, route_prefix=m.route_prefix,
            summary=module_summaries.get(module_key(m), ""),
            agg_hash=module_agg_hash(
                [f.content_hash for f in files if module_key(m) in f.modules]
            ),
            summary_embedding=(
                await fake_embedder.embed_texts(
                    [module_summaries.get(module_key(m), m.name)]
                )
            )[0],
        )
        for m in module_map.modules
    ]

    await write_project_graph(
        project_id, "mini-shop", "file://fixture", project_summary,
        modules_info, files, chunks, embed_texts, embeddings, api_edges,
        embed_keys=embed_keys,
    )
    return files, chunks, modules_info, api_edges


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
        files, chunks, modules, api_edges = await _index_fixture(pid, fake_embedder, fake_summarizer)

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
        await _index_fixture(pid, fake_embedder, fake_summarizer)
        await _index_fixture(pid_other, fake_embedder, fake_summarizer)

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
