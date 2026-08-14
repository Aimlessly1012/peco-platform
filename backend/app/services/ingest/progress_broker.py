"""索引进度的进程内发布订阅（M9 D1）。

只在单 worker 下正确：事件存在内存里，多 worker 时订阅者可能连到没有事件的那个进程。
现状 uvicorn 单 worker，扩 worker 需换 Redis pub/sub（DEPLOY.md 已注明）。

丢帧策略：队列满时丢最旧的一帧。进度流是"最新值有意义"的语义——
掉几个中间百分比无害，但阻塞 publish 会把索引管道也拖住，那是不可接受的。
"""
import asyncio
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 64
TERMINAL_STATUSES = ("succeeded", "failed")


class ProgressBroker:
    def __init__(self, maxsize: int = QUEUE_MAXSIZE) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._maxsize = maxsize
        self.dropped = 0        # 丢帧计数，便于排查"进度跳变"

    def publish(self, project_id: str, event: dict) -> None:
        """非阻塞投递。绝不 await——调用方是索引管道，不能因为没人读而卡住。"""
        queues = self._subscribers.get(str(project_id))
        if not queues:
            return
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 丢最旧的一帧腾位置：新进度比旧进度有价值
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
                self.dropped += 1

    @contextmanager
    def subscribe(self, project_id: str):
        """订阅某项目的进度。用 contextmanager 保证异常路径也会退订。"""
        key = str(project_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.setdefault(key, set()).add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(key)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscribers[key]   # 不留空集合，避免长期泄漏

    def subscriber_count(self, project_id: str) -> int:
        return len(self._subscribers.get(str(project_id), ()))


progress_broker = ProgressBroker()


def job_event(job) -> dict:
    """IndexJob → 进度事件。字段与 IndexJobOut 对齐，前端可直接复用类型。"""
    return {
        "job_id": str(job.id),
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "stats": job.stats_json or {},
        "error_text": job.error_text,
        "kind": job.kind,
    }


def is_terminal(event: dict) -> bool:
    return event.get("status") in TERMINAL_STATUSES
