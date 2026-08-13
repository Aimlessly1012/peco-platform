"""分层混合检索（M2）：module/file/chunk 三路向量 + RRF 融合 + 图扩展一跳。

独立于聊天 API（spec: 检索服务层独立可调用，后续 MCP 复用）。
"""
from dataclasses import dataclass, field

from app.core.config import settings
from app.graph.client import get_driver
from app.services.ingest.embedder import embedder
from app.services.retrieval import reranker

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
        """出处条目。顺序与提示词里的「资料 N」编号一一对应（N = 下标 + 1），
        答案中的 [n] 上标即按此定位，因此关联带出项也必须在列，不能过滤。"""
        return {
            "file_path": self.file_path or f"[模块] {self.symbol}",
            "start_line": self.start_line,
            "end_line": self.end_line,
            "node_id": self.node_id,
            "symbol": self.symbol,
            "kind": self.kind,          # chunk / file_summary / module_summary
            "via_edge": self.via_edge,  # None=直接命中；其余为关联带出的边类型
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


def _rerank_document(item: RetrievedItem) -> str:
    """送去精排的文档文本：chunk 是代码、摘要节点是摘要（D2）。

    带上文件路径与符号名作头——纯代码片段常常看不出它属于什么业务，
    重排模型拿到定位信息判得更准。
    """
    head = item.file_path or item.symbol
    if item.symbol and item.symbol not in ("(file)", head):
        head = f"{head} :: {item.symbol}"
    body = item.content or ""
    return f"{head}\n{body}" if head else body


async def _apply_rerank(
    query: str, items: list[RetrievedItem], final_k: int
) -> list[RetrievedItem]:
    """RRF 候选池 → 重排取 final_k。失败时保持 RRF 顺序（D2 降级）。"""
    if not items:
        return items
    ranking = await reranker.rerank(
        query, [_rerank_document(item) for item in items], top_n=final_k
    )
    if ranking is None:
        return items[:final_k]
    reordered: list[RetrievedItem] = []
    for index, score in ranking[:final_k]:
        item = items[index]
        item.score = score      # 分数改由重排模型给出，前端引用排序随之一致
        reordered.append(item)
    return reordered


async def search_layered(
    project_id: str, query: str, question_type: str = "local", top_k: int | None = None
) -> list[RetrievedItem]:
    """分层混合检索主入口（spec: 向量检索 MODIFIED）。

    global: module + file 摘要层为主 → 下钻代表块；local: chunk 为主 + file 辅助。
    M7：配置了 rerank 时，RRF 之后、图扩展之前插入精排——图扩展带出的是结构邻居，
    不该被文本相关性挤掉，所以精排只收敛主候选。impact 模式按图距离排序，不走精排。
    """
    k = top_k or settings.retrieval_top_k
    vec = await embedder.embed_query(query)
    # impact 的检索只用来定位目标文件，排序语义是图距离（D2）
    use_rerank = reranker.is_enabled() and question_type != "impact"

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
        final_k = k + 4
        pool = final_k * settings.rerank_candidate_multiplier if use_rerank else final_k
        merged = _rrf_merge(routes, top_k=pool)
    else:
        chunk_hits = await _vector_query("chunk_embedding", vec, project_id, k)
        file_hits = await _vector_query("file_summary_embedding", vec, project_id, max(2, k // 3))
        routes = [
            [_chunk_item(h["node"], h["score"]) for h in chunk_hits],
            [_file_item(h["node"], h["score"]) for h in file_hits],
        ]
        final_k = k
        pool = final_k * settings.rerank_candidate_multiplier if use_rerank else final_k
        merged = _rrf_merge(routes, top_k=pool)

    if use_rerank:
        merged = await _apply_rerank(query, merged, final_k)

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


# ---------------- 影响面多跳（M4 D4，聊天与 MCP 共用） ----------------

MAX_IMPACT_DEPTH = 3
MAX_IMPACT_RESULTS = 200


async def _resolve_impact_targets(project_id: str, file_or_symbol: str) -> list[str]:
    """起点解析：先当文件路径，找不到再当符号名反查其定义文件。"""
    key = (file_or_symbol or "").strip()
    if not key:
        return []
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:File {project_id: $pid, path: $path}) RETURN f.path AS p LIMIT 1",
            pid=project_id, path=key,
        )
        record = await result.single()
        if record is not None:
            return [record["p"]]
        result = await session.run(
            """
            MATCH (c:Chunk {project_id: $pid, symbol: $symbol})
            RETURN DISTINCT c.file_path AS p ORDER BY p LIMIT 5
            """,
            pid=project_id, symbol=key,
        )
        return [rec["p"] async for rec in result]


async def impact_of(
    project_id: str, file_or_symbol: str, max_depth: int = 2
) -> dict:
    """改动影响面：反向 IMPORTS 多跳 + CALLS_API 前端调用方 + 波及模块（设计 D4）。

    direct = 一跳引用者；transitive = 更深层（带 depth 与传播路径）。
    深度上限 3、结果上限 200——循环依赖的仓库不设限会指数膨胀。
    """
    depth = max(1, min(int(max_depth or 1), MAX_IMPACT_DEPTH))
    targets = await _resolve_impact_targets(project_id, file_or_symbol)
    if not targets:
        return {
            "target": file_or_symbol,
            "resolved_files": [],
            "max_depth": depth,
            "direct": [], "transitive": [],
            "frontend_callers": [], "modules_affected": [],
            "truncated": False,
        }

    driver = get_driver()
    async with driver.session() as session:
        # 变长路径的上界不能参数化，depth 已 clamp 成 1..3 的整数
        result = await session.run(
            f"""
            MATCH p = (f:File)-[:IMPORTS*1..{depth}]->(start:File)
            WHERE start.project_id = $pid AND start.path IN $paths
              AND f.project_id = $pid AND NOT f.path IN $paths
            WITH f.path AS path, f.summary AS summary,
                 length(p) AS d, [n IN nodes(p) | n.path] AS via
            ORDER BY d
            WITH path, summary, collect({{d: d, via: via}})[0] AS best
            RETURN path, summary, best.d AS depth, best.via AS via_path
            ORDER BY depth, path
            LIMIT $limit
            """,
            pid=project_id, paths=targets, limit=MAX_IMPACT_RESULTS,
        )
        rows = [
            {
                "file_path": rec["path"],
                "summary": (rec["summary"] or "")[:120],
                "depth": rec["depth"],
                "via_path": rec["via_path"],
            }
            async for rec in result
        ]

        affected = targets + [r["file_path"] for r in rows]
        result = await session.run(
            """
            MATCH (caller:Chunk {project_id: $pid})-[:CALLS_API]->(target:Chunk)
            WHERE target.file_path IN $affected
            RETURN DISTINCT caller.file_path AS path, caller.symbol AS symbol,
                   caller.start_line AS sl, caller.end_line AS el,
                   target.file_path AS target_file, target.symbol AS target_symbol
            ORDER BY path, sl
            LIMIT $limit
            """,
            pid=project_id, affected=affected, limit=MAX_IMPACT_RESULTS,
        )
        frontend_callers = [
            {
                "file_path": rec["path"],
                "symbol": rec["symbol"],
                "lines": f"{rec['sl']}-{rec['el']}",
                "calls": f"{rec['target_file']}:{rec['target_symbol']}",
            }
            async for rec in result
        ]

        module_scope = affected + [c["file_path"] for c in frontend_callers]
        result = await session.run(
            """
            MATCH (m:Module {project_id: $pid})-[:CONTAINS]->(f:File)
            WHERE f.path IN $paths
            RETURN m.module_name AS name, m.kind AS kind,
                   m.route_prefix AS prefix, count(DISTINCT f) AS files
            ORDER BY files DESC, name
            """,
            pid=project_id, paths=list(set(module_scope)),
        )
        modules_affected = [
            {
                "name": rec["name"], "kind": rec["kind"],
                "route_prefix": rec["prefix"] or "", "affected_files": rec["files"],
            }
            async for rec in result
        ]

    return {
        "target": file_or_symbol,
        "resolved_files": targets,
        "max_depth": depth,
        "direct": [r for r in rows if r["depth"] == 1],
        "transitive": [r for r in rows if r["depth"] > 1],
        "frontend_callers": frontend_callers,
        "modules_affected": modules_affected,
        "truncated": len(rows) >= MAX_IMPACT_RESULTS,
    }


def format_impact_context(impact: dict) -> str:
    """影响树 → 供 LLM 阅读的分层文本（聊天资料块，设计 D5）。"""
    target = ", ".join(impact["resolved_files"]) or impact["target"]
    lines = [f"影响面分析目标：{target}（反向依赖深度上限 {impact['max_depth']}）"]

    if impact["direct"]:
        lines.append("")
        lines.append("直接引用它的文件：")
        lines += [
            f"- {row['file_path']}：{row['summary'] or '（无摘要）'}"
            for row in impact["direct"]
        ]
    if impact["transitive"]:
        lines.append("")
        lines.append("间接受影响的文件（按传播深度）：")
        lines += [
            f"- [{row['depth']} 跳] {row['file_path']}"
            f"（路径：{' → '.join(reversed(row['via_path']))}）"
            for row in impact["transitive"]
        ]
    if impact["frontend_callers"]:
        lines.append("")
        lines.append("经 HTTP 调用受影响接口的前端代码块：")
        lines += [
            f"- {row['file_path']}:{row['lines']} {row['symbol']} → {row['calls']}"
            for row in impact["frontend_callers"]
        ]
    if impact["modules_affected"]:
        lines.append("")
        lines.append("波及的功能模块：")
        lines += [
            f"- [{row['kind']}] {row['name']}"
            f"{'（路由 ' + row['route_prefix'] + '）' if row['route_prefix'] else ''}"
            f"：{row['affected_files']} 个文件"
            for row in impact["modules_affected"]
        ]
    if not impact["direct"] and not impact["transitive"] and not impact["frontend_callers"]:
        lines.append("")
        lines.append("未发现其他文件引用它（可能是叶子模块或入口文件）。")
    if impact["truncated"]:
        lines.append("")
        lines.append(f"（结果已截断至 {MAX_IMPACT_RESULTS} 条）")
    return "\n".join(lines)
