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
from app.services.ingest.summarizer import FAILED_PREFIX, FAST_PREFIX

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
    # None = 从图读回但该节点没有 imports 属性（M4 前的老数据），需现场重提取
    imports: list[str] | None = field(default_factory=list)


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


async def load_feature_cache(project_id: str) -> dict[str, list[str]]:
    """agg_hash → 功能点（M6）。只复用 LLM 产出的那部分。

    降级（fallback）与 fast 的程序化功能点不入缓存——否则一次失败会被永久固化，
    重索引也拿不回真正的提取结果（与 L2 摘要的 FAST_PREFIX 排除同理）。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (m:Module {project_id: $pid})
            WHERE m.agg_hash IS NOT NULL AND m.features IS NOT NULL
              AND m.features_source = $source
            RETURN m.agg_hash AS h, m.features AS points
            """,
            pid=project_id, source="llm",
        )
        return {
            rec["h"]: list(rec["points"])
            async for rec in result
            if rec["h"] and rec["points"]
        }


async def save_module_features(project_id: str, points_by_hash: dict[str, list[str]]) -> int:
    """把 LLM 提取的功能点回写到 Module 节点（按 agg_hash 匹配），供下次索引复用。"""
    if not points_by_hash:
        return 0
    driver = get_driver()
    rows = [{"h": h, "points": points} for h, points in points_by_hash.items() if points]
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $rows AS row
            MATCH (m:Module {project_id: $pid, agg_hash: row.h})
            SET m.features = row.points, m.features_source = 'llm'
            RETURN count(m) AS n
            """,
            pid=project_id, rows=rows,
        )
        record = await result.single()
        return (record and record["n"]) or 0


async def load_project_index_meta(project_id: str) -> dict:
    """读回 Project 节点上记录的嵌入模型（M4 B15）。

    M4 之前写入的节点没有这两个属性，返回空 dict——调用方据此当作"模型未知"强制全量，
    因为无从判断存量向量出自哪个模型。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Project {project_id: $pid})
            RETURN p.embedding_model AS model, p.embedding_dim AS dim LIMIT 1
            """,
            pid=project_id,
        )
        record = await result.single()
        if record is None:
            return {}
        return {"embedding_model": record["model"], "embedding_dim": record["dim"]}


async def load_file_metadata(project_id: str) -> dict[str, FileInfo]:
    """读回图中已有的 File 节点（增量：未变更文件不再读盘解析 AST，设计 D1）。

    imports 属性是 M4 起新增的缓存；老数据缺失时返回 None，由调用方现场重提取。
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:File {project_id: $pid})
            RETURN f.path AS path, f.language AS language, f.content_hash AS hash,
                   f.summary AS summary, f.imports AS imports
            """,
            pid=project_id,
        )
        loaded: dict[str, FileInfo] = {}
        async for rec in result:
            path = rec["path"]
            if not path:
                continue
            info = FileInfo(
                path=path,
                language=rec["language"] or "",
                content_hash=rec["hash"] or "",
                summary=rec["summary"] or "",
            )
            # None = 老数据无该属性（需重提取）；[] = 确实没有 import
            info.imports = list(rec["imports"]) if rec["imports"] is not None else None
            loaded[path] = info
        return loaded


async def load_chunk_metadata(project_id: str, paths: set[str]) -> list[CodeChunk]:
    """读回指定文件的 Chunk（增量：CALLS_API 全局重算需要未变更文件的代码文本）。"""
    if not paths:
        return []
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Chunk {project_id: $pid}) WHERE c.file_path IN $paths
            RETURN c.file_path AS file_path, c.language AS language, c.symbol AS symbol,
                   c.symbol_type AS symbol_type, c.start_line AS start_line,
                   c.end_line AS end_line, c.code AS code, c.content_hash AS content_hash
            ORDER BY c.file_path, c.start_line
            """,
            pid=project_id, paths=list(paths),
        )
        return [
            CodeChunk(
                file_path=rec["file_path"] or "",
                language=rec["language"] or "",
                symbol=rec["symbol"] or "",
                symbol_type=rec["symbol_type"] or "",
                start_line=rec["start_line"] or 0,
                end_line=rec["end_line"] or 0,
                code=rec["code"] or "",
                content_hash=rec["content_hash"] or "",
            )
            async for rec in result
        ]


async def load_summary_cache(project_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """(file content_hash → L2 摘要, module agg_hash → L3 摘要)——M2 摘要缓存预读。"""
    driver = get_driver()
    file_cache: dict[str, str] = {}
    module_cache: dict[str, str] = {}
    async with driver.session() as session:
        # 失败占位与 fast 模式占位都不进缓存：前者要重试，后者要在 deep 补跑时被替换
        result = await session.run(
            "MATCH (f:File {project_id: $pid}) "
            "WHERE f.summary IS NOT NULL AND f.summary <> '' "
            "AND NOT f.summary STARTS WITH $failed AND NOT f.summary STARTS WITH $fast "
            "RETURN f.content_hash AS h, f.summary AS s",
            pid=project_id, failed=FAILED_PREFIX, fast=FAST_PREFIX,
        )
        file_cache = {rec["h"]: rec["s"] async for rec in result}
        result = await session.run(
            "MATCH (m:Module {project_id: $pid}) "
            "WHERE m.summary IS NOT NULL AND m.summary <> '' AND m.agg_hash IS NOT NULL "
            "AND NOT m.summary STARTS WITH $fast "
            "RETURN m.agg_hash AS h, m.summary AS s",
            pid=project_id, fast=FAST_PREFIX,
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
    edge_files: list[FileInfo] | None = None,
    edge_chunks: list[CodeChunk] | None = None,
) -> None:
    store = get_store()
    embed_keys = embed_keys or {}
    # 增量时节点集是变更文件、边集是全项目：未变更文件不重写节点，但仍要参与
    # CONTAINS/IMPORTS/CALLS_API 的重连（设计 D1：结构边全量重连）
    all_files = edge_files if edge_files is not None else files
    all_chunks = edge_chunks if edge_chunks is not None else chunks

    project_node = EntityNode(
        name=project_id,
        label="Project",
        properties={
            "project_id": project_id,
            "display_name": project_name,
            "git_url": git_url,
            "summary": project_summary,
            # 本次索引所用的嵌入模型：换模型后 auto 必须强制全量，
            # 否则未变更文件会留着上一个模型的向量（M4 B15）
            "embedding_model": settings.embedding_model,
            "embedding_dim": settings.embedding_dim,
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
                # M4 D1/B3：增量时未变更文件的 imports 从这里读回，不再读盘解析 AST。
                # IMPORTS 边仍是唯一真相源，本属性只作缓存。
                "imports": f.imports or [],
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
    file_paths = {f.path for f in all_files}
    for f in all_files:
        for mod_key in f.modules:  # f.modules 存 qualified key
            relations.append(
                rel("CONTAINS", module_node_name(project_id, mod_key),
                    file_node_name(project_id, f.path))
            )
        for target in f.imports or ():
            if target in file_paths:
                relations.append(
                    rel("IMPORTS", file_node_name(project_id, f.path),
                        file_node_name(project_id, target))
                )
    chunk_names = {(c.file_path, c.symbol, c.start_line): chunk_node_name(project_id, c) for c in chunks}
    by_file_symbol: dict[tuple[str, str], str] = {}
    for c in all_chunks:
        by_file_symbol.setdefault((c.file_path, c.symbol), chunk_node_name(project_id, c))
    # DEFINES 只对本次写入的节点生成：未变更文件的 DEFINES 边没被删过，重复写是浪费
    for c in chunks:
        relations.append(
            rel("DEFINES", file_node_name(project_id, c.file_path),
                chunk_names[(c.file_path, c.symbol, c.start_line)])
        )
    all_chunk_names = {
        (c.file_path, c.symbol, c.start_line): chunk_node_name(project_id, c)
        for c in all_chunks
    }
    for e in api_edges:
        source = all_chunk_names.get((e.source_file, e.source_symbol, e.source_start_line)) \
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
    edge_files: list[FileInfo] | None = None,
    edge_chunks: list[CodeChunk] | None = None,
) -> None:
    """同步 store 放线程池执行，避免阻塞事件循环。

    edge_files/edge_chunks 为增量模式提供"边的全集"：节点只写变更部分，
    但 CONTAINS/IMPORTS/CALLS_API 覆盖全项目（设计 D1）。
    """
    await asyncio.to_thread(
        _write_sync, project_id, project_name, git_url, project_summary,
        modules, files, chunks, context_texts, embeddings, api_edges, embed_keys,
        edge_files, edge_chunks,
    )
