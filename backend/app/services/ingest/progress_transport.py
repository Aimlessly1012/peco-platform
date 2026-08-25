"""索引进度的跨进程传输（M13 D4）。

M9 的 progress_broker 是进程内广播；M13 把索引挪进独立的 Celery worker 容器后，
worker 里 publish 的进度到不了持有 SSE 连接的 API 进程。这里补上中间那一段：

    worker: _update_job → progress_broker.publish → mirror → RabbitMQ fanout
    API:    消费 fanout → progress_broker.publish → SSE 端点 → 浏览器

浏览器侧的事件名与载荷结构一个字段没变（job_event 原样搬运），前端零改动。

两侧都刻意做成"坏了也不影响主流程"：
- worker 侧 publish 只往内存队列 put_nowait，绝不阻塞索引管道；队列满就丢帧，
  与 progress_broker 既有的丢帧哲学一致（进度是"最新值有意义"的语义）
- API 侧消费断线自动重连，重连期间最多少看几个中间百分比；任务终态始终能从
  IndexJob 表查到（spec: 任务状态单一事实源），不依赖这条通道

用 kombu（Celery 自带依赖）而不是另引消息库：broker 已经在那儿了，不该为进度
再分裂出第二套连接管理。
"""
import asyncio
import logging
import queue
import threading
from collections.abc import Callable

from app.core.config import settings
from app.services.ingest.progress_broker import progress_broker

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "rag.progress"
MIRROR_QUEUE_MAXSIZE = 256
RECONNECT_DELAY = 3.0
DRAIN_TIMEOUT = 1.0      # 也是 stop() 的最坏响应时间


def _exchange():
    """fanout 交换机。非 durable：进度是易失数据，broker 重启后重新声明即可。"""
    from kombu import Exchange

    return Exchange(EXCHANGE_NAME, type="fanout", durable=False)


class ProgressMirror:
    """worker 侧：进度帧 → RabbitMQ fanout。

    publish 在索引管道的调用栈里，必须瞬时返回，所以真正的网络发送交给后台
    daemon 线程，两者之间用有界队列隔开。
    """

    def __init__(self, url: str, maxsize: int = MIRROR_QUEUE_MAXSIZE) -> None:
        self._url = url
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.published = 0

    # ---- 生产侧（索引管道线程）----

    def publish(self, project_id: str, event: dict) -> None:
        """把一帧进度交给后台线程。队列满即丢弃——绝不阻塞管道。"""
        try:
            self._queue.put_nowait({"project_id": str(project_id), "event": event})
        except queue.Full:
            self.dropped += 1

    # ---- 消费侧（后台线程）----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, name="progress-mirror", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._pump()
            except Exception as e:  # noqa: BLE001 — 连接层任何异常都只是重连理由
                if self._stopping.is_set():
                    return
                logger.warning("进度镜像连接中断，%.0fs 后重连：%s", RECONNECT_DELAY, e)
                self._stopping.wait(RECONNECT_DELAY)

    def _pump(self) -> None:
        from kombu import Connection

        exchange = _exchange()
        with Connection(self._url) as conn:
            producer = conn.Producer(serializer="json")
            logger.info("进度镜像已连上 RabbitMQ（exchange=%s）", EXCHANGE_NAME)
            while not self._stopping.is_set():
                try:
                    payload = self._queue.get(timeout=DRAIN_TIMEOUT)
                except queue.Empty:
                    continue
                producer.publish(payload, exchange=exchange, declare=[exchange])
                self.published += 1


class ProgressConsumer:
    """API 侧：RabbitMQ fanout → 进程内 progress_broker。

    每个 API 进程一条 exclusive + auto_delete 队列：进程退出队列自动消失，
    不会在 broker 里攒下没人消费的死队列。多副本部署时每个副本各收一份全量，
    各自只把自己有订阅者的项目推给前端（progress_broker.publish 自带这个过滤）。
    """

    def __init__(self, url: str, sink: Callable[[str, dict], None]) -> None:
        self._url = url
        self._sink = sink
        self._stopping = threading.Event()
        self._task: asyncio.Task | None = None
        self.received = 0
        self.malformed = 0

    def handle(self, body, message=None) -> None:
        """收到一帧。坏帧丢掉即可，绝不能让消费循环因此断开。"""
        if message is not None:
            message.ack()
        project_id = body.get("project_id") if isinstance(body, dict) else None
        event = body.get("event") if isinstance(body, dict) else None
        if not project_id or not isinstance(event, dict):
            self.malformed += 1
            logger.warning("丢弃结构非法的进度帧：%r", body)
            return
        self.received += 1
        self._sink(str(project_id), event)

    # ---- 线程侧 ----

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._consume()
            except Exception as e:  # noqa: BLE001 — 同上，断线只是重连理由
                if self._stopping.is_set():
                    return
                logger.warning("进度消费中断，%.0fs 后重连：%s", RECONNECT_DELAY, e)
                self._stopping.wait(RECONNECT_DELAY)

    def _consume(self) -> None:
        from kombu import Connection, Queue

        # 队列名留空 = 由 broker 生成唯一名，配合 exclusive 保证每进程独占
        q = Queue(
            "", exchange=_exchange(), routing_key="",
            exclusive=True, auto_delete=True, durable=False,
        )
        with Connection(self._url) as conn:
            with conn.Consumer(q, callbacks=[self.handle], accept=["json"]):
                logger.info("进度消费者已就绪（exchange=%s）", EXCHANGE_NAME)
                while not self._stopping.is_set():
                    try:
                        conn.drain_events(timeout=DRAIN_TIMEOUT)
                    except TimeoutError:
                        continue          # 空闲一秒，回头看一眼要不要停

    # ---- 事件循环侧 ----

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(asyncio.to_thread(self.run))

    async def aclose(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("进度消费者未在 %.0fs 内退出，不再等待", timeout)
        finally:
            self._task = None


def install_worker_mirror(url: str | None = None) -> ProgressMirror:
    """worker 进程启动时调一次：此后管道里每帧进度都会镜像到 RabbitMQ。"""
    mirror = ProgressMirror(url or settings.rabbitmq_url)
    mirror.start()
    progress_broker.set_mirror(mirror.publish)
    logger.info("worker 进度镜像已装载")
    return mirror


async def start_progress_consumer(url: str | None = None) -> ProgressConsumer:
    """API 进程启动时调一次：消费 worker 的进度帧，转成进程内广播。"""
    loop = asyncio.get_running_loop()

    def sink(project_id: str, event: dict) -> None:
        # 消费跑在线程里，而 progress_broker.publish 要碰 asyncio.Queue，
        # 必须回到事件循环线程执行，否则 QueueFull/唤醒行为都不可靠
        loop.call_soon_threadsafe(progress_broker.publish, project_id, event)

    consumer = ProgressConsumer(url or settings.rabbitmq_url, sink)
    await consumer.start()
    return consumer
