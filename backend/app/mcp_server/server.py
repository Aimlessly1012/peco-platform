"""MCP 七工具（设计 D5）：全部复用既有检索服务层与图数据，不重复检索逻辑。

约定：
- 每个工具成功时都带 resolved_project_id，agent 可用它消除重名歧义
- 任何失败返回结构化错误 dict（见 resolver.error），不抛裸异常
- 代码定位一律 `文件路径 + 行号区间`，代码片段截断 80 行
"""
import logging

from sqlalchemy import desc, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.mcp_server.resolver import error, resolve_project
from app.models.tables import Project, ProjectStatus, UnderstandingReport
from app.services.report.graph_reader import (
    read_file_detail,
    read_impact,
    read_project_stats,
    read_project_tree,
    resolve_symbol_files,
)
from app.services.report.mindmap import build_mindmap
from app.services.retrieval.service import search_layered

logger = logging.getLogger(__name__)

MAX_TOP_K = 20
SNIPPET_MAX_LINES = 80
SUMMARY_HEAD_CHARS = 80
MAX_IMPACT_TARGETS = 3


def _truncate_snippet(code: str, max_lines: int = SNIPPET_MAX_LINES) -> str:
    lines = (code or "").splitlines()
    if len(lines) <= max_lines:
        return code or ""
    return "\n".join(lines[:max_lines]) + f"\n… （共 {len(lines)} 行，已截断）"


def _summary_head(summary: str, limit: int = SUMMARY_HEAD_CHARS) -> str:
    """L3 摘要首行（摘要格式为「业务目标：…\\n关键流程：…」，首行最能代表模块）。"""
    head = (summary or "").strip().splitlines()[0] if (summary or "").strip() else ""
    return head[:limit]


def _create_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="rag-coder",
        instructions=(
            "RAG Coder 代码库理解服务：把已索引的代码仓库以模块地图、文件摘要、"
            "语义检索与影响面分析的形式提供给编码 agent。"
            "先用 list_projects 拿到项目名，再用 get_project_overview 建立整体认识，"
            "然后用 search_code 定位代码、用 impact_analysis 评估改动波及范围。"
        ),
    )

    @server.tool()
    async def list_projects() -> dict:
        """列出后台已接入的全部代码项目（含索引状态、模块数与语言分布）。

        这是所有其他工具的入口：其余工具的 project 参数用这里返回的 name 或 id。
        """
        async with SessionLocal() as session:
            rows = list(
                await session.scalars(select(Project).order_by(desc(Project.created_at)))
            )
        projects = []
        for p in rows:
            stats = {"modules_count": 0, "languages": []}
            if p.status == ProjectStatus.READY:
                try:
                    stats = await read_project_stats(str(p.id))
                except Exception as e:  # noqa: BLE001 — 图不可用不该让整个清单失败
                    logger.warning("读取项目 %s 图统计失败：%s", p.name, e)
            projects.append(
                {
                    "id": str(p.id),
                    "name": p.name,
                    "status": p.status,
                    "modules_count": stats["modules_count"],
                    "languages": stats["languages"],
                }
            )
        return {"projects": projects, "count": len(projects)}

    @server.tool()
    async def get_project_overview(project: str) -> dict:
        """项目整体认识：项目级总览摘要 + 全部功能模块（名称/类型/路由前缀/一句话职责）。

        接手一个陌生项目时先调这个。project 传项目名称或 id。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        tree = await read_project_tree(str(found.id))
        return {
            "resolved_project_id": str(found.id),
            "project_name": tree.name or found.name,
            "summary": tree.summary,
            "modules": [
                {
                    "name": m.name,
                    "kind": m.kind,
                    "prefix": m.route_prefix,
                    "files_count": len(m.files),
                    "summary_head": _summary_head(m.summary),
                }
                for m in tree.modules
            ],
        }

    @server.tool()
    async def get_module_map(project: str) -> dict:
        """功能模块地图：mermaid 思维导图源码 + 每个模块包含的文件清单。

        想知道"某功能的代码分布在哪些文件"时用它。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        tree = await read_project_tree(str(found.id))
        return {
            "resolved_project_id": str(found.id),
            "mermaid_mindmap": build_mindmap(tree),
            "modules": [
                {
                    "name": m.name,
                    "kind": m.kind,
                    "prefix": m.route_prefix,
                    "files": [f.path for f in m.files],
                }
                for m in tree.modules
            ],
        }

    @server.tool()
    async def search_code(
        project: str, query: str, module: str | None = None, top_k: int = 5
    ) -> dict:
        """按自然语言语义检索项目代码，返回带文件路径与行号的代码片段。

        query 用中文或英文描述要找的功能（如"订单创建逻辑"）而非关键字匹配。
        module 可选，填模块名只在该模块内检索。top_k 上限 20，代码片段最多 80 行。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        if not query or not query.strip():
            return error("参数 query 不能为空，请用一句话描述要找的功能")

        pid = str(found.id)
        k = max(1, min(int(top_k or 5), MAX_TOP_K))

        allowed_paths: set[str] | None = None
        if module and module.strip():
            tree = await read_project_tree(pid)
            key = module.strip().lower()
            matched = [
                m for m in tree.modules
                if key in (m.name.lower(), m.key.lower()) or key in m.name.lower()
            ]
            if not matched:
                return error(
                    f"项目「{found.name}」中没有名为「{module}」的模块",
                    resolved_project_id=pid,
                    available_modules=[m.name for m in tree.modules],
                )
            allowed_paths = {f.path for m in matched for f in m.files}

        items = await search_layered(pid, query.strip(), "local", top_k=k)
        results = []
        for item in items:
            if allowed_paths is not None and item.file_path not in allowed_paths:
                continue
            results.append(
                {
                    "file_path": item.file_path or f"[模块] {item.symbol}",
                    "lines": f"{item.start_line}-{item.end_line}" if item.file_path else "",
                    "symbol": item.symbol,
                    "kind": item.kind,               # chunk / file_summary / module_summary
                    "symbol_type": item.symbol_type,  # function / class / file / module
                    "snippet": _truncate_snippet(item.content),
                    "via_edge": item.via_edge,       # None=直接命中；calls_api/imports/defines_file
                }
            )
            if len(results) >= k:
                break
        return {
            "resolved_project_id": pid,
            "query": query.strip(),
            "module": module or None,
            "count": len(results),
            "results": results,
        }

    @server.tool()
    async def get_file_summary(project: str, path: str) -> dict:
        """单个文件的职责摘要、符号清单（含行号）与依赖关系（imports / imported_by）。

        path 用仓库内相对路径，如 backend/routers/orders.py。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        if not path or not path.strip():
            return error("参数 path 不能为空，请传仓库内相对路径")

        pid = str(found.id)
        detail = await read_file_detail(pid, path.strip())
        if detail is None:
            return error(
                f"项目「{found.name}」中没有文件「{path}」",
                resolved_project_id=pid,
                hint="路径需为仓库内相对路径，可先用 get_module_map 查看文件清单",
            )
        return {"resolved_project_id": pid, **detail}

    @server.tool()
    async def impact_analysis(project: str, file_or_symbol: str) -> dict:
        """改动影响面（一跳反查）：谁 import 了它、哪些前端代码块经 HTTP 调用它、波及哪些模块。

        file_or_symbol 传文件相对路径或函数/类名（符号会先反查其定义文件）。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        if not file_or_symbol or not file_or_symbol.strip():
            return error("参数 file_or_symbol 不能为空")

        pid = str(found.id)
        key = file_or_symbol.strip()
        targets: list[str] = []
        if await read_file_detail(pid, key) is not None:
            targets = [key]
        else:
            targets = await resolve_symbol_files(pid, key)
        if not targets:
            return error(
                f"项目「{found.name}」中找不到文件或符号「{key}」",
                resolved_project_id=pid,
                hint="可先用 search_code 定位它所在的文件路径",
            )

        imported_by: dict[str, dict] = {}
        api_callers: dict[tuple, dict] = {}
        modules: dict[str, dict] = {}
        for target in targets[:MAX_IMPACT_TARGETS]:
            impact = await read_impact(pid, target)
            for row in impact["imported_by"]:
                imported_by[row["file_path"]] = row
            for row in impact["api_callers"]:
                api_callers[(row["file_path"], row["lines"])] = row
            for row in impact["modules_affected"]:
                modules[f"{row['kind']}:{row['name']}"] = row
        return {
            "resolved_project_id": pid,
            "resolved_files": targets[:MAX_IMPACT_TARGETS],
            "imported_by": list(imported_by.values()),
            "api_callers": list(api_callers.values()),
            "modules_affected": list(modules.values()),
        }

    @server.tool()
    async def get_project_understanding(project: str) -> dict:
        """项目理解报告三件套：需求逻辑文档（Markdown）、功能思维导图、核心流程时序图。

        索引时自动生成。想快速吃透一个项目的业务逻辑时用它。
        """
        found, err = await resolve_project(project)
        if err:
            return err
        async with SessionLocal() as session:
            report = await session.scalar(
                select(UnderstandingReport).where(
                    UnderstandingReport.project_id == found.id
                )
            )
        if report is None:
            return error(
                f"项目「{found.name}」还没有理解报告",
                resolved_project_id=str(found.id),
                hint="该项目的索引早于报告功能上线，请在后台重新索引以生成报告",
            )
        return {
            "resolved_project_id": str(found.id),
            "project_name": found.name,
            "doc_markdown": report.doc_markdown,
            "mindmap_mermaid": report.mindmap_mermaid,
            "sequences": report.sequences_json or [],
            "generated_at": report.generated_at.isoformat(),
        }

    return server


mcp = _create_server()


def mcp_http_app():
    """streamable-http ASGI 应用（路径 /mcp）。

    必须在 FastAPI lifespan 里 `async with mcp.session_manager.run():` —— Starlette 的
    Mount 不传播 lifespan，子应用自带的 lifespan 不会被触发（设计 D4 的版本坑）。
    """
    from mcp.server.transport_security import TransportSecuritySettings

    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=settings.mcp_allowed_origins,
        ),
    )
