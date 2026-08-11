import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.graph.client import close_driver, ensure_vector_index
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
    await _recover_stale_jobs()
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    yield
    await close_driver()


app = FastAPI(title="RAG Coder", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


from app.api.projects import router as projects_router  # noqa: E402
from app.api.chat import router as chat_router  # noqa: E402

app.include_router(projects_router)
app.include_router(chat_router)
