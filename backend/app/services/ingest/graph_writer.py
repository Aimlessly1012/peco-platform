"""Neo4j 图写入：Neo4jPropertyGraphStore 手动插入（设计 D1，M2 扩展）。

M2 图 schema：
  (:Project {summary})-[:HAS_MODULE]->(:Module {summary, embedding})
      -[:CONTAINS]->(:File {summary, embedding})-[:DEFINES]->(:Chunk {embedding})
  (:File)-[:IMPORTS]->(:File)
  (:Chunk)-[:CALLS_API]->(:Chunk)
所有节点带 project_id 属性做项目隔离。
"""
import asyncio
from dataclasses import dataclass, field

from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from app.core.config import settings
from app.graph.client import get_driver
from app.services.ingest.api_matcher import ApiEdge
from app.services.ingest.chunker import CodeChunk

_store: Neo4jPropertyGraphStore | None = None

UPSERT_BATCH = 500


def get_store() -> Neo4jPropertyGraphStore:
    global _store
    if _store is None:
        _store = Neo4jPropertyGraphStore(
            username=settings.neo4j_user,
            password=settings.neo4j_password,
            url=settings.neo4j_uri,
            refresh_schema=False,
        )
    return _store


@dataclass
class FileInfo:
    path: str
    language: str
    content_hash: str
    summary: str = ""
    summary_embedding: list[float] | None = None
    modules: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    name: str            # 显示名
    key: str             # 唯一键 "kind:name"（归属与节点名用它）
    kind: str
    route_prefix: str
    summary: str = ""
    agg_hash: str = ""
    summary_embedding: list[float] | None = None


def file_node_name(project_id: str, path: str) -> str:
    return f"{project_id}:{path}"


def module_node_name(project_id: str, name: str) -> str:
    return f"{project_id}:module:{name}"


def chunk_node_name(project_id: str, chunk: CodeChunk) -> str:
    return f"{project_id}:{chunk.file_path}:{chunk.symbol}:{chunk.start_line}"


async def load_embedding_cache(project_id: str) -> dict[str, list[float]]:
    """embed_key（嵌入文本 hash）→ chunk embedding（全量重建前预读，D5 复用向量）。

    M2 修正：缓存键为嵌入文本 hash 而非代码 hash——摘要/模块归属变化时向量随之失效重算。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (c:Chunk {project_id: $pid}) "
            "WHERE c.embedding IS NOT NULL AND c.embed_key IS NOT NULL "
            "RETURN c.embed_key AS h, c.embedding AS e",
            pid=project_id,
        )
        return {rec["h"]: rec["e"] async for rec in result}


async def load_summary_cache(project_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """(file content_hash → L2 摘要, module agg_hash → L3 摘要)——M2 摘要缓存预读。"""
    driver = get_driver()
    file_cache: dict[str, str] = {}
    module_cache: dict[str, str] = {}
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:File {project_id: $pid}) "
            "WHERE f.summary IS NOT NULL AND f.summary <> '' AND NOT f.summary STARTS WITH '（摘要生成失败' "
            "RETURN f.content_hash AS h, f.summary AS s",
            pid=project_id,
        )
        file_cache = {rec["h"]: rec["s"] async for rec in result}
        result = await session.run(
            "MATCH (m:Module {project_id: $pid}) "
            "WHERE m.summary IS NOT NULL AND m.summary <> '' AND m.agg_hash IS NOT NULL "
            "RETURN m.agg_hash AS h, m.summary AS s",
            pid=project_id,
        )
        module_cache = {rec["h"]: rec["s"] async for rec in result}
    return file_cache, module_cache


def _write_sync(
    project_id: str,
    project_name: str,
    git_url: str,
    project_summary: str,
    modules: list[ModuleInfo],
    files: list[FileInfo],
    chunks: list[CodeChunk],
    context_texts: dict[str, str],
    embeddings: dict[str, list[float]],
    api_edges: list[ApiEdge],
    embed_keys: dict[str, str] | None = None,
) -> None:
    store = get_store()
    embed_keys = embed_keys or {}

    project_node = EntityNode(
        name=project_id,
        label="Project",
        properties={
            "project_id": project_id,
            "display_name": project_name,
            "git_url": git_url,
            "summary": project_summary,
        },
    )
    module_nodes = [
        EntityNode(
            name=module_node_name(project_id, m.key),
            label="Module",
            embedding=m.summary_embedding,
            properties={
                "project_id": project_id,
                "module_name": m.name,  # 避免与 EntityNode.name（节点 id）冲突
                "kind": m.kind,
                "route_prefix": m.route_prefix,
                "summary": m.summary,
                "agg_hash": m.agg_hash,
            },
        )
        for m in modules
    ]
    file_nodes = [
        EntityNode(
            name=file_node_name(project_id, f.path),
            label="File",
            embedding=f.summary_embedding,
            properties={
                "project_id": project_id,
                "path": f.path,
                "language": f.language,
                "content_hash": f.content_hash,
                "summary": f.summary,
            },
        )
        for f in files
    ]
    chunk_nodes = [
        EntityNode(
            name=chunk_node_name(project_id, c),
            label="Chunk",
            embedding=embeddings.get(c.content_hash),
            properties={
                "project_id": project_id,
                "file_path": c.file_path,
                "language": c.language,
                "symbol": c.symbol,
                "symbol_type": c.symbol_type,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "code": c.code,
                "context_text": context_texts.get(c.content_hash, ""),
                "content_hash": c.content_hash,
                "embed_key": embed_keys.get(c.content_hash, ""),
            },
        )
        for c in chunks
    ]

    def rel(label: str, source: str, target: str) -> Relation:
        return Relation(
            label=label, source_id=source, target_id=target,
            properties={"project_id": project_id},
        )

    relations: list[Relation] = []
    for m in modules:
        relations.append(rel("HAS_MODULE", project_id, module_node_name(project_id, m.key)))
    file_paths = {f.path for f in files}
    for f in files:
        for mod_key in f.modules:  # f.modules 存 qualified key
            relations.append(
                rel("CONTAINS", module_node_name(project_id, mod_key),
                    file_node_name(project_id, f.path))
            )
        for target in f.imports:
            if target in file_paths:
                relations.append(
                    rel("IMPORTS", file_node_name(project_id, f.path),
                        file_node_name(project_id, target))
                )
    chunk_names = {(c.file_path, c.symbol, c.start_line): chunk_node_name(project_id, c) for c in chunks}
    by_file_symbol: dict[tuple[str, str], str] = {}
    for c in chunks:
        by_file_symbol.setdefault((c.file_path, c.symbol), chunk_node_name(project_id, c))
    for c in chunks:
        relations.append(
            rel("DEFINES", file_node_name(project_id, c.file_path),
                chunk_names[(c.file_path, c.symbol, c.start_line)])
        )
    for e in api_edges:
        source = chunk_names.get((e.source_file, e.source_symbol, e.source_start_line)) \
            or by_file_symbol.get((e.source_file, e.source_symbol))
        target = by_file_symbol.get((e.target_file, e.target_symbol))
        if source and target:
            relations.append(rel("CALLS_API", source, target))

    all_nodes = [project_node, *module_nodes, *file_nodes, *chunk_nodes]
    for i in range(0, len(all_nodes), UPSERT_BATCH):
        store.upsert_nodes(all_nodes[i : i + UPSERT_BATCH])
    for i in range(0, len(relations), UPSERT_BATCH):
        store.upsert_relations(relations[i : i + UPSERT_BATCH])


async def write_project_graph(
    project_id: str,
    project_name: str,
    git_url: str,
    project_summary: str,
    modules: list[ModuleInfo],
    files: list[FileInfo],
    chunks: list[CodeChunk],
    context_texts: dict[str, str],
    embeddings: dict[str, list[float]],
    api_edges: list[ApiEdge],
    embed_keys: dict[str, str] | None = None,
) -> None:
    """同步 store 放线程池执行，避免阻塞事件循环。"""
    await asyncio.to_thread(
        _write_sync, project_id, project_name, git_url, project_summary,
        modules, files, chunks, context_texts, embeddings, api_edges, embed_keys,
    )
