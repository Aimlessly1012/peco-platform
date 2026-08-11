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
