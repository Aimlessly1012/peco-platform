"""图数据只读访问层（M3）：报告生成与 MCP 工具共用，不重复写 Cypher。

所有查询按 project_id 过滤（项目隔离），返回纯 dataclass / dict，不含 Neo4j 类型。
"""
import logging
from dataclasses import dataclass, field

from app.graph.client import get_driver

logger = logging.getLogger(__name__)


@dataclass
class FileNode:
    path: str
    language: str = ""
    summary: str = ""


@dataclass
class ModuleNode:
    key: str                 # "kind:name" 唯一键
    name: str
    kind: str                # page | api | dir | shared
    route_prefix: str = ""
    summary: str = ""
    files: list[FileNode] = field(default_factory=list)


@dataclass
class ProjectTree:
    project_id: str
    name: str = ""
    summary: str = ""
    modules: list[ModuleNode] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(m.files) for m in self.modules)


@dataclass
class ApiEdgeInfo:
    """CALLS_API：前端调用块 → 后端 handler 块。"""

    src_file: str
    src_symbol: str
    src_start: int
    dst_file: str
    dst_symbol: str
    dst_start: int


@dataclass
class ImportEdgeInfo:
    src: str
    dst: str


@dataclass
class GraphEdges:
    api_edges: list[ApiEdgeInfo] = field(default_factory=list)
    import_edges: list[ImportEdgeInfo] = field(default_factory=list)


def _module_key_from_node(node_name: str) -> str:
    """节点名形如 "{project_id}:module:{kind}:{name}"，取 ":module:" 之后为唯一键。"""
    marker = ":module:"
    idx = node_name.find(marker)
    return node_name[idx + len(marker):] if idx >= 0 else node_name


async def read_project_tree(project_id: str) -> ProjectTree:
    """读 Project→Module→File 树（思维导图 / 功能地图 / MCP get_module_map 共用）。"""
    driver = get_driver()
    tree = ProjectTree(project_id=project_id)
    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Project {project_id: $pid}) "
            "RETURN p.display_name AS name, p.summary AS summary LIMIT 1",
            pid=project_id,
        )
        record = await result.single()
        if record is not None:
            tree.name = record["name"] or ""
            tree.summary = record["summary"] or ""

        result = await session.run(
            """
            MATCH (p:Project {project_id: $pid})-[:HAS_MODULE]->(m:Module)
            OPTIONAL MATCH (m)-[:CONTAINS]->(f:File)
            WITH m, f ORDER BY f.path
            RETURN m.name AS node_name, m.module_name AS name, m.kind AS kind,
                   m.route_prefix AS prefix, m.summary AS summary,
                   collect(f {.path, .language, .summary}) AS files
            ORDER BY m.kind, m.module_name
            """,
            pid=project_id,
        )
        async for rec in result:
            files = [
                FileNode(
                    path=f.get("path") or "",
                    language=f.get("language") or "",
                    summary=f.get("summary") or "",
                )
                for f in (rec["files"] or [])
                if f and f.get("path")
            ]
            tree.modules.append(
                ModuleNode(
                    key=_module_key_from_node(rec["node_name"] or ""),
                    name=rec["name"] or "",
                    kind=rec["kind"] or "",
                    route_prefix=rec["prefix"] or "",
                    summary=rec["summary"] or "",
                    files=files,
                )
            )
    return tree


async def read_graph_edges(project_id: str) -> GraphEdges:
    """一次性读全项目 CALLS_API / IMPORTS 边（时序图输入，按模块在内存中过滤）。"""
    driver = get_driver()
    edges = GraphEdges()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (src:Chunk {project_id: $pid})-[:CALLS_API]->(dst:Chunk)
            RETURN src.file_path AS sf, src.symbol AS ss, src.start_line AS sl,
                   dst.file_path AS df, dst.symbol AS ds, dst.start_line AS dl
            """,
            pid=project_id,
        )
        async for rec in result:
            edges.api_edges.append(
                ApiEdgeInfo(
                    src_file=rec["sf"] or "", src_symbol=rec["ss"] or "",
                    src_start=rec["sl"] or 0,
                    dst_file=rec["df"] or "", dst_symbol=rec["ds"] or "",
                    dst_start=rec["dl"] or 0,
                )
            )
        result = await session.run(
            """
            MATCH (a:File {project_id: $pid})-[:IMPORTS]->(b:File)
            RETURN a.path AS src, b.path AS dst
            """,
            pid=project_id,
        )
        async for rec in result:
            edges.import_edges.append(
                ImportEdgeInfo(src=rec["src"] or "", dst=rec["dst"] or "")
            )
    return edges


async def read_file_detail(project_id: str, path: str) -> dict | None:
    """MCP get_file_summary：L2 摘要 + 符号清单 + imports / imported_by。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:File {project_id: $pid, path: $path})
            OPTIONAL MATCH (f)-[:DEFINES]->(c:Chunk)
            WITH f, c ORDER BY c.start_line
            RETURN f.path AS path, f.language AS language, f.summary AS summary,
                   collect(c {.symbol, .symbol_type, .start_line, .end_line}) AS symbols
            LIMIT 1
            """,
            pid=project_id, path=path,
        )
        record = await result.single()
        if record is None:
            return None
        symbols = [
            {
                "name": s.get("symbol") or "",
                "type": s.get("symbol_type") or "",
                "lines": f"{s.get('start_line') or 0}-{s.get('end_line') or 0}",
            }
            for s in (record["symbols"] or [])
            if s and s.get("symbol")
        ]
        result = await session.run(
            """
            MATCH (f:File {project_id: $pid, path: $path})-[:IMPORTS]->(t:File)
            RETURN t.path AS p ORDER BY p
            """,
            pid=project_id, path=path,
        )
        imports = [rec["p"] async for rec in result]
        result = await session.run(
            """
            MATCH (s:File {project_id: $pid})-[:IMPORTS]->(f:File {path: $path})
            RETURN s.path AS p ORDER BY p
            """,
            pid=project_id, path=path,
        )
        imported_by = [rec["p"] async for rec in result]
        result = await session.run(
            """
            MATCH (m:Module {project_id: $pid})-[:CONTAINS]->(f:File {path: $path})
            RETURN m.module_name AS n, m.kind AS k ORDER BY n
            """,
            pid=project_id, path=path,
        )
        modules = [f"{rec['k']}:{rec['n']}" async for rec in result]
    return {
        "path": record["path"],
        "language": record["language"] or "",
        "summary": record["summary"] or "",
        "symbols": symbols,
        "imports": imports,
        "imported_by": imported_by,
        "modules": modules,
    }


async def resolve_symbol_files(project_id: str, symbol: str) -> list[str]:
    """file_or_symbol 传符号名时，反查定义它的文件路径（impact_analysis 用）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Chunk {project_id: $pid, symbol: $symbol})
            RETURN DISTINCT c.file_path AS p ORDER BY p LIMIT 5
            """,
            pid=project_id, symbol=symbol,
        )
        return [rec["p"] async for rec in result]


async def read_impact(project_id: str, path: str) -> dict:
    """MCP impact_analysis：一跳反查（谁 import 我 / 谁 CALLS_API 调我 / 波及模块）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:File {project_id: $pid})-[:IMPORTS]->(f:File {path: $path})
            RETURN s.path AS p, s.summary AS s ORDER BY p
            """,
            pid=project_id, path=path,
        )
        imported_by = [
            {"file_path": rec["p"], "summary": (rec["s"] or "")[:120]} async for rec in result
        ]
        result = await session.run(
            """
            MATCH (caller:Chunk {project_id: $pid})-[:CALLS_API]->(target:Chunk)
            WHERE target.file_path = $path
            RETURN DISTINCT caller.file_path AS p, caller.symbol AS sym,
                   caller.start_line AS sl, caller.end_line AS el,
                   target.symbol AS tsym
            ORDER BY p, sl
            """,
            pid=project_id, path=path,
        )
        api_callers = [
            {
                "file_path": rec["p"],
                "symbol": rec["sym"],
                "lines": f"{rec['sl']}-{rec['el']}",
                "calls_handler": rec["tsym"],
            }
            async for rec in result
        ]
        affected_paths = [c["file_path"] for c in imported_by] + [
            c["file_path"] for c in api_callers
        ] + [path]
        result = await session.run(
            """
            MATCH (m:Module {project_id: $pid})-[:CONTAINS]->(f:File)
            WHERE f.path IN $paths
            RETURN DISTINCT m.module_name AS n, m.kind AS k, m.route_prefix AS r
            ORDER BY k, n
            """,
            pid=project_id, paths=list(set(affected_paths)),
        )
        modules_affected = [
            {"name": rec["n"], "kind": rec["k"], "route_prefix": rec["r"] or ""}
            async for rec in result
        ]
    return {
        "imported_by": imported_by,
        "api_callers": api_callers,
        "modules_affected": modules_affected,
    }


async def read_project_stats(project_id: str) -> dict:
    """MCP list_projects：模块数与语言分布（图不存在时返回零值，不抛异常）。"""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (m:Module {project_id: $pid})
            RETURN count(m) AS modules
            """,
            pid=project_id,
        )
        record = await result.single()
        modules = (record and record["modules"]) or 0
        result = await session.run(
            """
            MATCH (f:File {project_id: $pid})
            RETURN f.language AS lang, count(f) AS n ORDER BY n DESC LIMIT 8
            """,
            pid=project_id,
        )
        languages = [rec["lang"] async for rec in result if rec["lang"]]
    return {"modules_count": modules, "languages": languages}
