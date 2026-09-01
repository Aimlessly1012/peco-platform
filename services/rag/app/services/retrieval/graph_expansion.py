"""图扩展：外挂 Cypher 查询函数（M15 D2 风险条款 / spec「明确标注的外挂查询函数」）。

为什么这三路没有迁进 Neo4jVector 的 retrieval_query 插槽——不是懒，是迁进去会
改行为，而「行为零变化」是本次的验收红线：

- `expand_one_hop` 的种子是 **RRF 融合并精排之后**的 top-5 直接命中 chunk。
  retrieval_query 在向量命中的那一刻就执行，那时候 RRF 还没跑、rerank 更没跑，
  拿到的种子集合与现在不是一回事，扩展出来的邻居自然也不同。
- `representative_chunks` 的种子是 file 路的前 4 条，而产出要并进 **chunk 路**
  参与 RRF（score 记 0.0）。写进 file 路的插槽，它们就变成 file 路的条目、带着
  file 的分数进 RRF——融合排名会整个变样。

结论：插槽承载的是「单条命中能就地算出来的东西」（project 过滤、字段投影），
跨路、跨阶段的扩展只能留在外面。design 的风险条款与 spec 都明确允许这种混合形态。
"""
from app.graph.client import get_driver
from app.services.retrieval.models import RetrievedItem, chunk_item, file_item


async def representative_chunks(
    project_id: str, file_node_ids: list[str], per_file: int = 2
) -> list[RetrievedItem]:
    """摘要层命中的文件 → 沿 DEFINES 取前几个代表块下钻。"""
    if not file_node_ids:
        return []
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:File)-[:DEFINES]->(c:Chunk)
            WHERE f.name IN $ids AND f.project_id = $pid
            WITH f, c ORDER BY c.start_line
            WITH f, collect(c)[0..$per_file] AS reps
            UNWIND reps AS chunk
            RETURN chunk
            """,
            ids=file_node_ids, pid=project_id, per_file=per_file,
        )
        return [
            chunk_item(dict(r["chunk"]), 0.0, via="defines_file") async for r in result
        ]


async def expand_one_hop(
    project_id: str, chunk_node_ids: list[str]
) -> list[RetrievedItem]:
    """图扩展一跳（设计 D6）：所属文件 L2 / CALLS_API 对端 / IMPORTS 目标 L2。"""
    if not chunk_node_ids:
        return []
    driver = get_driver()
    expanded: list[RetrievedItem] = []
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Chunk)<-[:DEFINES]-(f:File)
            WHERE c.name IN $ids AND c.project_id = $pid
            RETURN DISTINCT f
            """,
            ids=chunk_node_ids, pid=project_id,
        )
        expanded.extend(
            [file_item(dict(r["f"]), 0.0, via="defines_file") async for r in result]
        )

        result = await session.run(
            """
            MATCH (c:Chunk)-[:CALLS_API]-(other:Chunk)
            WHERE c.name IN $ids AND c.project_id = $pid
            RETURN DISTINCT other
            """,
            ids=chunk_node_ids, pid=project_id,
        )
        expanded.extend(
            [chunk_item(dict(r["other"]), 0.0, via="calls_api") async for r in result]
        )

        result = await session.run(
            """
            MATCH (c:Chunk)<-[:DEFINES]-(:File)-[:IMPORTS]->(t:File)
            WHERE c.name IN $ids AND c.project_id = $pid
            RETURN DISTINCT t LIMIT 6
            """,
            ids=chunk_node_ids, pid=project_id,
        )
        expanded.extend(
            [file_item(dict(r["t"]), 0.0, via="imports") async for r in result]
        )
    return expanded


async def get_project_summary(project_id: str) -> str:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Project {project_id: $pid}) RETURN p.summary AS s LIMIT 1",
            pid=project_id,
        )
        record = await result.single()
        return (record and record["s"]) or ""
