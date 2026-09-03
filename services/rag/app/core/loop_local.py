"""按事件循环缓存资源。

## 解决的问题

asyncio 的同步原语（Semaphore / Lock）在**首次 await 时**绑定当时的运行循环；
httpx 的连接池（`AsyncOpenAI` 内部持有）同样绑定创建它的循环。而 Celery 每个
任务都用 `asyncio.run()` 起一个全新循环（见 `celery_tasks.py` 模块注释），
于是模块级单例里的这类资源跨任务复用时，第二个任务必然抛：

    RuntimeError: <asyncio.locks.Semaphore ... [locked]> is bound to a different event loop

线上表现是同一个 worker 子进程跑第二个索引任务时 `stage=summarize` 必炸。

## 为什么不沿用 celery_tasks 的清理式解法

那边对 DB 引擎池与 Neo4j driver 的做法是任务 `finally` 里显式 dispose。
它有效，但**要求每个调用方都记得清理**——本次的三处单例就是漏掉的证据，
而且漏掉时不报错，只在第二个任务才炸。

这里改成资源自己认循环：谁来取、在哪个循环里取，由资源自己判断要不要重建。
对调用方透明，Celery、FastAPI、测试三条路径同样受益，不依赖任何人记得。

## 旧值不做关闭

循环换掉时旧资源理应 `aclose()`，但那必须在**旧循环**里 await，而旧循环此刻
已经关了——跨循环调用只会抛新的错。所以这里直接丢弃引用：httpx 的 socket
随旧循环销毁而释放，代价是可能有 ResourceWarning，换来的是不引入一个
"清理动作自己会炸"的新故障点。
"""

import asyncio
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


def _current_loop() -> asyncio.AbstractEventLoop | None:
    """当前运行循环；不在异步上下文里返回 None（也当作一种 key，不特殊对待）。"""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class LoopLocal(Generic[T]):
    """惰性创建、并在事件循环变化时重建的资源持有者。

    用法：

        self._sem = LoopLocal(lambda: asyncio.Semaphore(settings.xxx_concurrency))
        async with self._sem.get():
            ...

    工厂函数在**取值时**调用，不是构造时——所以它读到的 settings 是当次运行的值，
    模块导入顺序不再影响并发上限。
    """

    __slots__ = ("_factory", "_value", "_loop", "_has_value")

    def __init__(self, factory: Callable[[], T]) -> None:
        # 传 lambda 而非绑定方法：绑定方法在构造时就固定了，之后替换类上的实现
        # （测试 monkeypatch、运行时换实现）不会生效，而那种失效是静默的
        self._factory = factory
        self._value: T | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # 单独记一个标志位而不是靠 _value is None：工厂返回 None 也算有效值
        self._has_value = False

    def get(self) -> T:
        loop = _current_loop()
        if not self._has_value or self._loop is not loop:
            self._value = self._factory()
            self._loop = loop
            self._has_value = True
        return self._value  # type: ignore[return-value]

    def reset(self) -> None:
        """丢弃当前值，下次 get 重建。给测试与显式回收用。"""
        self._value = None
        self._loop = None
        self._has_value = False
