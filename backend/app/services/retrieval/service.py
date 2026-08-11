"""分层混合检索（M2）：module/file/chunk 三路向量 + RRF 融合 + 图扩展一跳。

独立于聊天 API（spec: 检索服务层独立可调用，后续 MCP 复用）。
"""
from dataclasses import dataclass, field

from app.core.config import settings
from app.graph.client import get_driver
from app.services.ingest.embedder import embedder

RRF_K = 60


@dataclass
class RetrievedItem:
    kind: str            # chunk | file_summary | module_summary
    node_id: str
    file_path: str       # module_summary 时为空串
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int
    content: str         # 代码或摘要文本
    score: float
    via_edge: str | None = None  # None=直接命中；defines_file/calls_api/imports=关联带出

    def citation(self) -> dict:
        return {
            "file_path": self.file_path or f"[模块] {self.symbol}",
            "start_line": self.start_line,
            "end_line": self.end_line,
            "node_id": self.node_id,
            "symbol": self.symbol,
        }


async def _vector_query(
    index: str, vec: list[float], project_id: str, k: int
) -> list[dict]:
    driver = get_driver()
    async with driver.session() as session:
        # 向量索引不支持 pre-filter：over-fetch 4x 后按 project_id 过滤
        result = await session.run(
            f"""
            CALL db.index.vector.queryNodes('{index}', $fetch_k, $vec)
            YIELD node, score
            WHERE node.project_id = $pid
            RETURN node, score LIMIT $k
            """,
            fetch_k=k * 4, vec=vec, pid=project_id, k=k,
        )
        return [{"node": dict(r["node"]), "score": r["score"]} async for r in result]


def _chunk_item(props: dict, score: float, via: str | None = None) -> RetrievedItem:
    return RetrievedItem(
        kind="chunk",
        node_id=props.get("name", ""),
        file_path=props.get("file_path", ""),
        symbol=props.get("symbol", ""),
        symbol_type=props.get("symbol_type", ""),
        start_line=props.get("start_line", 0),
        end_line=props.get("end_line", 0),
        content=props.get("code", ""),
        score=score,
        via_edge=via,
    )


def _file_item(props: dict, score: float, via: str | None = None) -> RetrievedItem:
    return RetrievedItem(
        kind="file_summary",
        node_id=props.get("name", ""),
        file_path=props.get("path", ""),
        symbol="(file)",
        symbol_type="file",
        start_line=0,
        end_line=0,
        content=props.get("summary", ""),
        score=score,
        via_edge=via,
    )


def _module_item(props: dict, score: float) -> RetrievedItem:
    return RetrievedItem(
        kind="module_summary",
        node_id=props.get("name", ""),
        file_path="",
        symbol=props.get("module_name") or props.get("name", "").split(":module:")[-1],
        symbol_type="module",
        start_line=0,
        end_line=0,
        content=props.get("summary", ""),
        score=score,
    )


def _rrf_merge(routes: list[list[RetrievedItem]], top_k: int) -> list[RetrievedItem]:
    scores: dict[str, float] = {}
    items: dict[str, RetrievedItem] = {}
    for route in routes:
        for rank, item in enumerate(route):
            scores[item.node_id] = scores.get(item.node_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            if item.node_id not in items:
                items[item.node_id] = item
    merged = sorted(items.values(), key=lambda i: scores[i.node_id], reverse=True)
    for item in merged:
        item.score = scores[item.node_id]
    return merged[:top_k]


async def _representative_chunks(
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
        return [_chunk_item(dict(r["chunk"]), 0.0, via="defines_file") async for r in result]


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
        expanded.extend([_file_item(dict(r["f"]), 0.0, via="defines_file") async for r in result])

        result = await session.run(
            """
            MATCH (c:Chunk)-[:CALLS_API]-(other:Chunk)
            WHERE c.name IN $ids AND c.project_id = $pid
            RETURN DISTINCT other
            """,
            ids=chunk_node_ids, pid=project_id,
        )
        expanded.extend([_chunk_item(dict(r["other"]), 0.0, via="calls_api") async for r in result])

        result = await session.run(
            """
            MATCH (c:Chunk)<-[:DEFINES]-(:File)-[:IMPORTS]->(t:File)
            WHERE c.name IN $ids AND c.project_id = $pid
            RETURN DISTINCT t LIMIT 6
            """,
            ids=chunk_node_ids, pid=project_id,
        )
        expanded.extend([_file_item(dict(r["t"]), 0.0, via="imports") async for r in result])
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


async def search_layered(
    project_id: str, query: str, question_type: str = "local", top_k: int | None = None
) -> list[RetrievedItem]:
    """分层混合检索主入口（spec: 向量检索 MODIFIED）。

    global: module + file 摘要层为主 → 下钻代表块；local: chunk 为主 + file 辅助。
    """
    k = top_k or settings.retrieval_top_k
    vec = await embedder.embed_query(query)

    if question_type == "global":
        module_hits = await _vector_query("module_summary_embedding", vec, project_id, 4)
        file_hits = await _vector_query("file_summary_embedding", vec, project_id, 6)
        chunk_hits = await _vector_query("chunk_embedding", vec, project_id, k // 2)
        reps = await _representative_chunks(
            project_id, [h["node"].get("name", "") for h in file_hits[:4]]
        )
        routes = [
            [_module_item(h["node"], h["score"]) for h in module_hits],
            [_file_item(h["node"], h["score"]) for h in file_hits],
            [_chunk_item(h["node"], h["score"]) for h in chunk_hits] + reps,
        ]
        merged = _rrf_merge(routes, top_k=k + 4)
    else:
        chunk_hits = await _vector_query("chunk_embedding", vec, project_id, k)
        file_hits = await _vector_query("file_summary_embedding", vec, project_id, max(2, k // 3))
        routes = [
            [_chunk_item(h["node"], h["score"]) for h in chunk_hits],
            [_file_item(h["node"], h["score"]) for h in file_hits],
        ]
        merged = _rrf_merge(routes, top_k=k)

    # 图扩展一跳（直接命中的 chunk）
    hit_chunk_ids = [i.node_id for i in merged if i.kind == "chunk" and i.via_edge is None]
    expanded = await expand_one_hop(project_id, hit_chunk_ids[:5])
    existing_ids = {i.node_id for i in merged}
    for item in expanded:
        if item.node_id not in existing_ids:
            merged.append(item)
            existing_ids.add(item.node_id)

    return merged


async def search_chunks(project_id: str, query: str, top_k: int | None = None):
    """M1 兼容入口：局部检索。"""
    return await search_layered(project_id, query, "local", top_k)
