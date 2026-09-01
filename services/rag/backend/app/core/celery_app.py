"""Celery 实例（M13 D1-D3）。

broker 用 RabbitMQ；result backend 用 Postgres（db+ 前缀走同步 SQLAlchemy，
所以 URL 要剥掉 +asyncpg）——但 result 只供框架层排障，任务状态的唯一事实源
永远是 IndexJob 表（spec: 任务状态单一事实源），业务代码不许读 result。

acks_late + reject_on_worker_lost 是重启续跑语义的根基：worker 被杀（含 OOM）
时消息回到队列重投递，配合任务壳的幂等门（celery_tasks.py）实现自动续跑。
"""
from celery import Celery

from app.core.config import settings


def _result_backend_url() -> str:
    # postgresql+asyncpg://... → db+postgresql://...（celery db backend 走同步 psycopg2）
    return "db+" + settings.database_url.replace("+asyncpg", "")


celery_app = Celery(
    "rag_coder",
    broker=settings.rabbitmq_url,
    backend=_result_backend_url(),
    include=["app.services.ingest.celery_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # acks_late 配套：不预取——串行 worker 手里压着未 ack 的预取消息，
    # 重启时会整批重投递，进度观感是"跳回去又跑一遍"
    worker_prefetch_multiplier=1,
    task_default_queue="indexing",
    # durable 队列 + persistent 消息（spec: 重启自动续跑）。Celery 默认即
    # durable/persistent，这里显式写死防止未来"优化"时误关
    task_queues=None,
    task_default_delivery_mode="persistent",
    broker_connection_retry_on_startup=True,
    result_expires=7 * 24 * 3600,
    timezone="UTC",
)
