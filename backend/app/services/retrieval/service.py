"""分层混合检索（M2 → M15）：module/file/chunk 三路向量 + RRF 融合 + 图扩展一跳。

独立于聊天 API（spec: 检索服务层独立可调用，MCP 复用同一入口）。

M15 起本模块只做**编排**，三段实现各归其位：
    vector_store.py     三路 Neo4jVector（LangChain 组件 + retrieval_query 插槽）
    components.py       RRF 融合与 rerank（当代 1.x 风格自持组件，不引 classic）
    graph_expansion.py  跨路/跨阶段的图扩展（明确标注的外挂 Cypher，见该模块注释）

检索算法本身一点没动：三路 → RRF → （非 impact 时）精排 → 图扩展一跳追加。
"""
from app.core.config import settings
from app.services.retrieval import reranker
from app.services.retrieval.components import rrf_fuser, rerank_compressor
from app.services.retrieval.graph_expansion import (
    expand_one_hop,
    get_project_summary,
    representative_chunks,
)
from app.services.retrieval.models import RetrievedItem
from app.services.retrieval.vector_store import (
    CHUNK_INDEX,
    FILE_INDEX,
    MODULE_INDEX,
    embed_query,
    vector_route,
)
from app.graph.client import get_driver

# 对外保持 M14 的导入面：workflow / MCP / 测试都从本模块拿这些名字
__all__ = [
    "RetrievedItem", "search_layered", "search_chunks", "expand_one_hop",
    "get_project_summary", "impact_of", "format_impact_context",
    "MAX_IMPACT_DEPTH", "MAX_IMPACT_RESULTS",
]


async def search_layered(
    project_id: str, query: str, question_type: str = "local", top_k: int | None = None
) -> list[RetrievedItem]:
    """分层混合检索主入口（spec: 向量检索 MODIFIED）。

    global: module + file 摘要层为主 → 下钻代表块；local: chunk 为主 + file 辅助。
    M7：配置了 rerank 时，RRF 之后、图扩展之前插入精排——图扩展带出的是结构邻居，
    不该被文本相关性挤掉，所以精排只收敛主候选。impact 模式按图距离排序，不走精排。
    """
    k = top_k or settings.retrieval_top_k
    vec = await embed_query(query)
    # impact 的检索只用来定位目标文件，排序语义是图距离（D2）
    use_rerank = reranker.is_enabled() and question_type != "impact"

    if question_type == "global":
        modules = await vector_route(MODULE_INDEX, vec, project_id, 4, query)
        files = await vector_route(FILE_INDEX, vec, project_id, 6, query)
        chunks = await vector_route(CHUNK_INDEX, vec, project_id, k // 2, query)
        reps = await representative_chunks(
            project_id, [f.node_id for f in files[:4]]
        )
        routes = [modules, files, chunks + reps]
        final_k = k + 4
    else:
        chunks = await vector_route(CHUNK_INDEX, vec, project_id, k, query)
        files = await vector_route(FILE_INDEX, vec, project_id, max(2, k // 3), query)
        routes = [chunks, files]
        final_k = k

    pool = final_k * settings.rerank_candidate_multiplier if use_rerank else final_k
    merged = rrf_fuser.fuse(routes, top_k=pool)

    if use_rerank:
        merged = await rerank_compressor.compress(query, merged, final_k)

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
