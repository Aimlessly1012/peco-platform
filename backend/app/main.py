import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.meta import router as meta_router
from app.api.projects import router as projects_router
from app.core.config import settings
from app.core.db import SessionLocal
from app.graph.client import close_driver, ensure_vector_index
from app.mcp_server.auth import MCPAuthMiddleware
from app.services.auth.bootstrap import check_secret_key, ensure_admin_user
from app.mcp_server.server import mcp, mcp_http_app
from app.models.tables import IndexJob, JobStatus, Project, ProjectStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _recover_stale_jobs() -> None:
    """进程重启后，将 running 任务标记为 failed(stale)，项目状态回退（spec: 任务恢复语义）。"""
    async with SessionLocal() as session:
        result = await session.execute(
            update(IndexJob)
            .where(IndexJob.status == JobStatus.RUNNING)
            .values(status=JobStatus.FAILED, error_text="进程重启导致任务中断（stale），请重新触发索引")
            .returning(IndexJob.project_id)
        )
        stale_project_ids = [row[0] for row in result.fetchall()]
        if stale_project_ids:
            await session.execute(
                update(Project)
                .where(Project.id.in_(stale_project_ids))
                .values(status=ProjectStatus.FAILED)
            )
            logger.warning("恢复了 %d 个 stale 索引任务", len(stale_project_ids))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_vector_index()
    check_secret_key()          # M8：默认/过短的 SECRET_KEY 会让登录态可伪造
    await ensure_admin_user()   # M8：无 admin 且配了 ADMIN_PASSWORD 时创建
    await _recover_stale_jobs()
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    # MCP session manager 必须在这里启动：Starlette 的 Mount 不传播 lifespan，
    # 子应用自带的 lifespan 不会被触发（设计 D4）。
    async with mcp.session_manager.run():
        logger.info("MCP 端点已就绪：POST /mcp（streamable-http）")
        yield
    await close_driver()


def create_app() -> FastAPI:
    """应用工厂。

    每次调用都重建 MCP 子应用——StreamableHTTPSessionManager 的 run() 每实例只能进入一次，
    复用同一个实例的第二个 app 启动时会直接抛错（测试里连着起两个 app 就会踩到）。
    """
    app = FastAPI(title="RAG Coder", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3200"],
        # M8 登录态走 httpOnly cookie：本地开发跨端口（3200→9200）必须放行凭据，
        # 缺这行浏览器直接拦 preflight（生产同域不经 CORS，不受影响）
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # /mcp 是 mount 进来的子应用，依赖注入进不去，鉴权只能在 ASGI 层做（M4 D7）
    app.add_middleware(MCPAuthMiddleware, token=settings.mcp_auth_token, path="/mcp")
    if settings.mcp_auth_token:
        logger.info("MCP 鉴权已开启（MCP_AUTH_TOKEN）")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(chat_router)
    app.include_router(meta_router)

    # MCP 挂在根路径、且必须在业务路由之后注册：MCP 子应用内部持有 /mcp 路由，
    # 挂到 /mcp 会变成 /mcp/mcp（挂 /mcp 且子路径设 "/" 则 POST 会吃到 307 重定向）。
    # FastAPI 按注册顺序匹配，业务路由优先，未匹配的路径才落到 MCP 子应用。
    app.mount("/", mcp_http_app())
    return app


app = create_app()
