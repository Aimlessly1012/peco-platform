"""fixture 仓建图 helper（M17 3.2）。

原本是 test_pipeline_integration 里的私有函数，检索评测也要用同一套建图流程，
所以提升为共享 helper：空 Neo4j 上调一次即可得到完整的 Module/File/Chunk 图，
跑的是真实的 parse→summarize→embed→graph 段，只把 git 与外部模型换成测试替身。

用法（调用方自带 fake_embedder / fake_summarizer 夹具）：

    from tests.helpers.fixture_graph import FIXTURE_REPO, index_fixture_repo
    files, chunks, modules, api_edges = await index_fixture_repo(pid, fake_embedder, fake_summarizer)
"""
from pathlib import Path

from app.services.ingest.api_matcher import extract_api_edges
from app.services.ingest.graph_writer import ModuleInfo, write_project_graph
from app.services.ingest.module_mapper import (
    assign_files,
    ensure_shared_module,
    module_key,
)
from app.services.ingest.pipeline import _parse_all, build_embed_text, embed_cache_key
from app.services.ingest.router_parser import parse_routes
from app.services.ingest.summarizer import module_agg_hash
from app.services.ingest.walker import walk_repo

FIXTURE_REPO = Path(__file__).resolve().parent.parent / "fixtures" / "mini_repo"

__all__ = ["FIXTURE_REPO", "index_fixture_repo"]


async def index_fixture_repo(project_id: str, fake_embedder, fake_summarizer):
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
        embed_keys[c.content_hash] = embed_cache_key(text)
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
            # 与 pipeline 的写法保持一致（M6 B7），否则集成测试覆盖不到路由写入
            route_paths=[f"{path}|{entry}" for path, entry in m.route_paths],
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
