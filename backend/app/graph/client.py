import logging

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.core.config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

VECTOR_INDEX_NAME = "chunk_embedding"

# M2: 索引名 → (节点标签, 向量属性)
VECTOR_INDEXES: dict[str, tuple[str, str]] = {
    "chunk_embedding": ("Chunk", "embedding"),
    "file_summary_embedding": ("File", "embedding"),
    "module_summary_embedding": ("Module", "embedding"),
}


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def ensure_vector_index() -> None:
    """启动时幂等创建三个向量索引；任一已存在但维度不符则拒绝启动（设计 D2/M2 D5）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "SHOW INDEXES YIELD name, options WHERE name IN $names",
            names=list(VECTOR_INDEXES.keys()),
        )
        existing = {r["name"]: r["options"] async for r in result}
        for name, (label, prop) in VECTOR_INDEXES.items():
            if name in existing:
                existing_dim = existing[name]["indexConfig"].get("vector.dimensions")
                if int(existing_dim) != settings.embedding_dim:
                    raise RuntimeError(
                        f"Neo4j 向量索引 {name} 维度为 {existing_dim}，"
                        f"与 EMBEDDING_DIM={settings.embedding_dim} 不符。"
                        f"如确认更换嵌入模型，请执行 DROP INDEX {name} 并重新索引全部项目。"
                    )
                continue
            await session.run(
                f"""
                CREATE VECTOR INDEX {name} IF NOT EXISTS
                FOR (n:{label}) ON (n.{prop})
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: $dim,
                  `vector.similarity_function`: 'cosine'
                }}}}
                """,
                dim=settings.embedding_dim,
            )
            logger.info("已创建 Neo4j 向量索引 %s (dim=%d)", name, settings.embedding_dim)


async def delete_project_graph(project_id: str) -> None:
    """删除某项目在 Neo4j 中的全部节点与边（项目删除 / 全量重建前调用）。"""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (n {project_id: $pid}) DETACH DELETE n", pid=project_id
        )


async def delete_files_subgraph(project_id: str, paths: list[str]) -> int:
    """删除指定文件的 File 节点及其 DEFINES 的 Chunk（增量：删除/改名/修改的文件）。

    返回删除的节点数。DETACH DELETE 会同时清掉这些节点的所有入边
    （别处指向它们的 IMPORTS/CONTAINS/CALLS_API），这也是结构边必须全量重连的原因。
    """
    if not paths:
        return 0
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:File {project_id: $pid}) WHERE f.path IN $paths
            OPTIONAL MATCH (f)-[:DEFINES]->(c:Chunk)
            WITH collect(DISTINCT f) + collect(DISTINCT c) AS nodes
            UNWIND nodes AS n
            DETACH DELETE n
            RETURN count(n) AS deleted
            """,
            pid=project_id, paths=paths,
        )
        record = await result.single()
        return (record and record["deleted"]) or 0


async def delete_modules_and_structural_edges(project_id: str) -> None:
    """增量前置：删掉全部 Module 节点与残留的 IMPORTS/CALLS_API 边。

    Module 节点整体重建（模块划分是全局计算，可能增删改），DETACH DELETE 顺带清掉
    HAS_MODULE/CONTAINS；DEFINES 不动（File→自身 Chunk，非全局计算，未变更文件要复用）。
    """
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Module {project_id: $pid}) DETACH DELETE m", pid=project_id
        )
        await session.run(
            """
            MATCH ()-[r:IMPORTS]->() WHERE r.project_id = $pid DELETE r
            """,
            pid=project_id,
        )
        await session.run(
            """
            MATCH ()-[r:CALLS_API]->() WHERE r.project_id = $pid DELETE r
            """,
            pid=project_id,
        )
