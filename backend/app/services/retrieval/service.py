"""检索服务层：向量 top-k + project_id 过滤。

独立于聊天 API（spec: 检索服务层独立可调用，后续 MCP 复用）。
"""
from dataclasses import dataclass

from app.core.config import settings
from app.graph.client import VECTOR_INDEX_NAME, get_driver
from app.services.ingest.embedder import embedder


@dataclass
class RetrievedChunk:
    node_id: str
    file_path: str
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int
    code: str
    score: float

    def citation(self) -> dict:
        return {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "node_id": self.node_id,
            "symbol": self.symbol,
        }


async def search_chunks(
    project_id: str, query: str, top_k: int | None = None
) -> list[RetrievedChunk]:
    k = top_k or settings.retrieval_top_k
    query_vector = await embedder.embed_query(query)
    driver = get_driver()
    async with driver.session() as session:
        # 向量索引不支持 pre-filter：over-fetch 4x 后按 project_id 过滤（M1 项目数少，足够）
        result = await session.run(
            f"""
            CALL db.index.vector.queryNodes('{VECTOR_INDEX_NAME}', $fetch_k, $vec)
            YIELD node, score
            WHERE node.project_id = $pid
            RETURN node.name AS node_id, node.file_path AS file_path,
                   node.symbol AS symbol, node.symbol_type AS symbol_type,
                   node.start_line AS start_line, node.end_line AS end_line,
                   node.code AS code, score
            LIMIT $k
            """,
            fetch_k=k * 4,
            vec=query_vector,
            pid=project_id,
            k=k,
        )
        records = await result.data()
    return [
        RetrievedChunk(
            node_id=r["node_id"],
            file_path=r["file_path"],
            symbol=r["symbol"],
            symbol_type=r["symbol_type"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            code=r["code"],
            score=r["score"],
        )
        for r in records
    ]
