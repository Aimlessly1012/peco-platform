import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.meta import router as meta_router
from app.api.projects import router as projects_router
from app.core.config import settings
from app.core.db import SessionLocal
from app.graph.client import close_driver, ensure_vector_index
from app.mcp_server.auth import MCPAuthMiddleware
from app.mcp_server.server import mcp, mcp_http_app
from app.models.tables import IndexJob, JobStatus, Project, ProjectStatus
from app.services.auth.bootstrap import check_secret_key
from app.services.retrieval.vector_store import reset_stores
from app.services.storage.minio_client import ensure_bucket_quietly

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _recover_stale_jobs() -> None:
    """进程重启后的在途任务处理。

    M13 起分两条路：开了任务队列就把 RUNNING 的任务重新入队（spec: 启动时孤儿任务
    回收——重投而非标 failed，幂等门保证与 broker 里可能还在的那条消息双跑无害）；
    没开队列时保持 M12 行为，标 failed(stale) 等人重新触发。
    """
    if settings.task_queue_enabled:
        await _requeue_stale_jobs()
        return
    await _fail_stale_jobs()


async def _requeue_stale_jobs() -> None:
    """把孤儿 RUNNING 任务重新投递。投递失败只告警——不能因为 broker 没起来就拒绝启动。"""
    from app.services.ingest.celery_tasks import enqueue_index_job
    from app.services.ingest.pipeline import requested_params

    async with SessionLocal() as session:
        rows = await session.scalars(
            select(IndexJob).where(IndexJob.status == JobStatus.RUNNING)
        )
        pending = [(j.id, j.project_id, *requested_params(j)) for j in rows]

    requeued = 0
    for job_id, project_id, mode, depth in pending:
        try:
            enqueue_index_job(job_id, project_id, mode, depth)
            requeued += 1
        except Exception as e:  # noqa: BLE001 — 单个投递失败不该拖垮启动
            logger.warning("孤儿任务 %s 重新入队失败：%s", job_id, e)
    if pending:
        logger.warning("孤儿 RUNNING 任务 %d 个，已重新入队 %d 个", len(pending), requeued)


async def _fail_stale_jobs() -> None:
    """进程内执行时代的语义：running 任务标 failed(stale)，项目状态回退。"""
    async with SessionLocal() as session:
        result = await session.execute(
            update(IndexJob)
            .where(IndexJob.status == JobStatus.RUNNING)
            .values(
                status=JobStatus.FAILED,
                error_text="进程重启导致任务中断（stale），请重新触发索引",
            )
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


async def _start_progress_consumer():
    """M13 D4：开了任务队列才需要跨进程进度——索引在别的容器里跑。"""
    if not settings.task_queue_enabled:
        return None
    from app.services.ingest.progress_transport import start_progress_consumer

    try:
        return await start_progress_consumer()
    except Exception as e:  # noqa: BLE001 — 进度是增强项，连不上不该拦住启动
        logger.warning("进度消费者启动失败，SSE 只能看到本进程事件：%s", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_vector_index()
    check_secret_key()  # M8：默认/过短的 SECRET_KEY 会让登录态可伪造
    await _recover_stale_jobs()
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(ensure_bucket_quietly)  # M13：MinIO 桶（非关键路径）
    consumer = await _start_progress_consumer()
    try:
        # MCP session manager 必须在这里启动：Starlette 的 Mount 不传播 lifespan，
        # 子应用自带的 lifespan 不会被触发（设计 D4）。
        async with mcp.session_manager.run():
            logger.info("MCP 端点已就绪：POST /mcp（streamable-http）")
            yield
    finally:
        if consumer is not None:
            await consumer.aclose()
        # M15：Neo4jVector 用的是自己的同步驱动，async close_driver() 关不到它
        reset_stores()
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
