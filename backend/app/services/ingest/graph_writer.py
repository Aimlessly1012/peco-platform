"""Neo4j 图写入：Neo4jPropertyGraphStore 手动插入（设计 D1，M2 扩展无迁移）。

M1 图 schema：
  (:Project)-[:HAS_FILE]->(:File)-[:DEFINES]->(:Chunk)
所有节点带 project_id 属性做项目隔离。
"""
import asyncio
from dataclasses import dataclass

from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from app.core.config import settings
from app.graph.client import get_driver
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


def file_node_name(project_id: str, path: str) -> str:
    return f"{project_id}:{path}"


def chunk_node_name(project_id: str, chunk: CodeChunk) -> str:
    return f"{project_id}:{chunk.file_path}:{chunk.symbol}:{chunk.start_line}"


async def load_embedding_cache(project_id: str) -> dict[str, list[float]]:
    """读取该项目已有块的 content_hash → embedding 映射（全量重建前调用，D5 复用向量）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (c:Chunk {project_id: $pid}) WHERE c.embedding IS NOT NULL "
            "RETURN c.content_hash AS h, c.embedding AS e",
            pid=project_id,
        )
        return {rec["h"]: rec["e"] async for rec in result}


def _write_sync(
    project_id: str,
    project_name: str,
    git_url: str,
    files: list[FileInfo],
    chunks: list[CodeChunk],
    context_texts: dict[str, str],
    embeddings: dict[str, list[float]],
) -> None:
    store = get_store()

    project_node = EntityNode(
        name=project_id,
        label="Project",
        properties={"project_id": project_id, "display_name": project_name, "git_url": git_url},
    )
    file_nodes = [
        EntityNode(
            name=file_node_name(project_id, f.path),
            label="File",
            properties={
                "project_id": project_id,
                "path": f.path,
                "language": f.language,
                "content_hash": f.content_hash,
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
            },
        )
        for c in chunks
    ]

    relations = [
        Relation(
            label="HAS_FILE",
            source_id=project_node.id,
            target_id=file_node_name(project_id, f.path),
            properties={"project_id": project_id},
        )
        for f in files
    ] + [
        Relation(
            label="DEFINES",
            source_id=file_node_name(project_id, c.file_path),
            target_id=chunk_node_name(project_id, c),
            properties={"project_id": project_id},
        )
        for c in chunks
    ]

    all_nodes = [project_node, *file_nodes, *chunk_nodes]
    for i in range(0, len(all_nodes), UPSERT_BATCH):
        store.upsert_nodes(all_nodes[i : i + UPSERT_BATCH])
    for i in range(0, len(relations), UPSERT_BATCH):
        store.upsert_relations(relations[i : i + UPSERT_BATCH])


async def write_project_graph(
    project_id: str,
    project_name: str,
    git_url: str,
    files: list[FileInfo],
    chunks: list[CodeChunk],
    context_texts: dict[str, str],
    embeddings: dict[str, list[float]],
) -> None:
    """同步 store 放线程池执行，避免阻塞事件循环。"""
    await asyncio.to_thread(
        _write_sync, project_id, project_name, git_url,
        files, chunks, context_texts, embeddings,
    )
