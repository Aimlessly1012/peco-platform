"""索引任务的 Celery 壳（M13 D1）。

同步 task 入口里 asyncio.run 现有的 async pipeline——run_index_job 一行没改。
每个任务一个全新事件循环，避开 Celery prefork 与长驻 loop 的兼容坑。

两处是这一层的全部要害，改动前先读注释：

1. **幂等门**。acks_late + reject_on_worker_lost 意味着同一条消息可能被投递多次
   （worker 被杀、启动时孤儿回收都会重投），任务开头必须能识别"这活已经干完了"
   并直接返回。判据是 IndexJob 的 status——它是任务状态的唯一事实源。

2. **任务尾清池**。asyncio.run 每次新建事件循环，而 asyncpg 与 neo4j 的连接池里
   缓存着绑定在上一个循环上的连接；不清池，第二个任务必然炸
   "attached to a different loop"。engine.dispose() 与 close_driver() 放在 finally，
   任务成功失败都要走到。
"""
import asyncio
import logging
import uuid

from celery.signals import worker_process_init

from app.core import db as core_db
from app.core.celery_app import celery_app
from app.core.config import settings
from app.graph import client as graph_client
from app.core.db import SessionLocal
from app.models.tables import IndexJob, JobStatus

logger = logging.getLogger(__name__)

TASK_NAME = "index.run"
TERMINAL_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)

# 任务壳的返回值只进 Celery result backend（供排障），业务一律读 IndexJob
RESULT_DONE = "done"
RESULT_SKIPPED = "skipped"


@worker_process_init.connect
def _install_progress_mirror(**_kwargs) -> None:
    """worker 子进程起来时装进度镜像（M13 D4）。

    挂 worker_process_init 而不是 worker_init：prefork 下任务跑在子进程里，
    镜像线程必须和管道同进程。--max-tasks-per-child 换子进程时会再触发一次。
    """
    from app.services.ingest.progress_transport import install_worker_mirror

    # 仓库副本目录由 API 进程在 lifespan 里建；worker 是独立容器，自己也得兜一手
    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    install_worker_mirror()


async def _should_run(job_id: uuid.UUID) -> bool:
    """幂等门：job 不存在或已终态 → 这条消息是重复投递，直接放过。"""
    async with SessionLocal() as session:
        job = await session.get(IndexJob, job_id)
    if job is None:
        logger.warning("索引任务 %s 已不存在（项目被删？），跳过", job_id)
        return False
    if job.status in TERMINAL_STATUSES:
        logger.info("索引任务 %s 已是 %s，跳过重复投递", job_id, job.status)
        return False
    return True


async def _run_with_cleanup(
    job_id: uuid.UUID, project_id: uuid.UUID, mode: str, depth: str
) -> str:
    from app.services.ingest.pipeline import run_index_job

    try:
        if not await _should_run(job_id):
            return RESULT_SKIPPED
        await run_index_job(job_id, project_id, mode, depth)
        return RESULT_DONE
    finally:
        # 见模块注释第 2 点：不清池，下一个任务必炸 attached to a different loop
        await core_db.engine.dispose()
        await graph_client.close_driver()


@celery_app.task(name=TASK_NAME, bind=True, ignore_result=False)
def run_index_task(
    self, job_id: str, project_id: str, mode: str, depth: str
) -> str:
    """Celery 入口。参数全用 str：UUID 不是 JSON 原生类型。"""
    return asyncio.run(
        _run_with_cleanup(uuid.UUID(job_id), uuid.UUID(project_id), mode, depth)
    )


def enqueue_index_job(
    job_id: uuid.UUID, project_id: uuid.UUID, mode: str, depth: str
) -> str:
    """投递一个索引任务，返回 Celery task id。broker 不可用时抛异常，由调用方处理。"""
    async_result = run_index_task.delay(str(job_id), str(project_id), mode, depth)
    logger.info("索引任务已入队：job=%s celery_task=%s", job_id, async_result.id)
    return async_result.id
