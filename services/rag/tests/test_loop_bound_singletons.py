"""模块级单例跨事件循环复用的回归测试。

## 背景

Celery 每个任务用 `asyncio.run()` 起新循环（见 `celery_tasks.py` 模块注释），
而 `summarizer` / `embedder` / `report_llm` 是模块级单例，内部的 `asyncio.Semaphore`
与 `AsyncOpenAI`（httpx 连接池）会绑死首次使用时的循环。线上表现：同一个 worker
子进程跑第二个索引任务时 `stage=summarize` 必炸
`RuntimeError: ... is bound to a different event loop`。

## 这些测试为什么要制造并发竞争

**Semaphore 只在产生真正的等待者时才绑定循环。** 单次 `async with sem` 不会绑，
所以「跑两次 asyncio.run 各 acquire 一次」这种写法**测不出问题**——它在修复前
也是绿的。定位这个 bug 时先写的就是那样一条，一度误以为无法复现。

因此下面每条都让并发数超过信号量上限（`+2`），逼出等待者。
`test_bare_semaphore_still_breaks_across_loops` 把这个前提本身钉死：它用裸
Semaphore 复现旧行为，如果哪天 Python 改了语义使它不再抛错，那条会失败并提醒
我们——上面几条的防护也就失去了意义，而不是继续绿着假装还在保护。
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.loop_local import LoopLocal
from app.services.ingest.embedder import embedder
from app.services.ingest.summarizer import summarizer
from app.services.report.llm import report_llm


class _FakeChat:
    """够用的 chat.completions.create 替身：慢一点，让并发真的重叠。"""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_kw):
        await asyncio.sleep(0.005)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, *, input, **_kw):  # noqa: A002
        await asyncio.sleep(0.005)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0]) for _ in input])


def _twice(async_fn) -> None:
    """连续两个独立事件循环里各跑一次。第二次是回归点。

    注意 `asyncio.gather` 必须在循环**内**调用，所以传进来的是 async 函数，
    不是已经建好的 gather 对象。
    """
    asyncio.run(async_fn())
    asyncio.run(async_fn())


# ── LoopLocal 本身 ────────────────────────────────────────────────


def test_loop_local_reuses_value_within_one_loop():
    calls = []
    local = LoopLocal(lambda: (calls.append(1), object())[1])

    async def use():
        return local.get() is local.get()

    assert asyncio.run(use()) is True
    assert len(calls) == 1


def test_loop_local_rebuilds_when_loop_changes():
    made = []
    local = LoopLocal(lambda: (made.append(1), object())[1])

    async def use():
        local.get()

    asyncio.run(use())
    asyncio.run(use())
    assert len(made) == 2, "换了事件循环应当重建"


def test_loop_local_reset_forces_rebuild():
    made = []
    local = LoopLocal(lambda: (made.append(1), object())[1])

    async def use():
        local.get()
        local.reset()
        local.get()

    asyncio.run(use())
    assert len(made) == 2


def test_loop_local_caches_falsy_value():
    """工厂返回 None / 0 也算有效值，不能每次重建。"""
    made = []
    local = LoopLocal(lambda: (made.append(1), None)[1])

    async def use():
        local.get()
        local.get()

    asyncio.run(use())
    assert len(made) == 1


# ── 三个单例的跨循环回归 ──────────────────────────────────────────


def test_summarizer_survives_a_second_event_loop(monkeypatch):
    # patch `client` property 而不是 `_make_client`：前者在修复前后都存在，
    # 这条测试因此能在旧实现上以「跨事件循环」这个正确原因失败，而不是 AttributeError
    monkeypatch.setattr(type(summarizer), "client", property(lambda self: _FakeChat()))
    n = settings.summary_concurrency + 2  # 超过上限 → 必然产生等待者

    async def factory():
        await asyncio.gather(*[summarizer._complete("p") for _ in range(n)])

    _twice(factory)


def test_embedder_survives_a_second_event_loop(monkeypatch):
    # patch `client` property 而不是 `_make_client`：前者在修复前后都存在，
    # 这条测试因此能在旧实现上以「跨事件循环」这个正确原因失败，而不是 AttributeError
    monkeypatch.setattr(type(embedder), "client", property(lambda self: _FakeEmbeddings()))
    n = settings.embedding_concurrency + 2

    async def factory():
        await asyncio.gather(*[embedder._embed_once(["t"]) for _ in range(n)])

    _twice(factory)


def test_report_llm_survives_a_second_event_loop(monkeypatch):
    # patch `client` property 而不是 `_make_client`：前者在修复前后都存在，
    # 这条测试因此能在旧实现上以「跨事件循环」这个正确原因失败，而不是 AttributeError
    monkeypatch.setattr(type(report_llm), "client", property(lambda self: _FakeChat()))
    n = settings.summary_concurrency + 2

    async def factory():
        await asyncio.gather(*[report_llm._complete("p", 100) for _ in range(n)])

    _twice(factory)


def test_client_is_rebuilt_per_loop(monkeypatch):
    """连 AsyncOpenAI 一起跟着循环走——httpx 连接池同样绑定创建它的循环。"""
    made: list[object] = []

    def make(self):
        c = _FakeChat()
        made.append(c)
        return c

    monkeypatch.setattr(type(summarizer), "_make_client", make)

    async def touch():
        summarizer.client  # noqa: B018

    asyncio.run(touch())
    asyncio.run(touch())
    assert len(made) == 2, "换循环后客户端应当重建"


# ── 前提锚点 ──────────────────────────────────────────────────────


def test_bare_semaphore_still_breaks_across_loops():
    """钉住上面几条成立的前提：裸 Semaphore 在有竞争时确实跨循环即炸。

    这条失败意味着 Python 的语义变了——那时要重新评估 LoopLocal 是否还有必要，
    而不是让上面的测试继续绿着假装在保护什么。
    """
    sem = asyncio.Semaphore(1)

    async def contend():
        async def one():
            async with sem:
                await asyncio.sleep(0.005)

        await asyncio.gather(one(), one())

    asyncio.run(contend())
    with pytest.raises(RuntimeError, match="bound to a different event loop"):
        asyncio.run(contend())


def test_single_acquire_does_not_reproduce():
    """反向锚点：不制造竞争就测不出问题——记录这个陷阱，别把上面的并发简化掉。"""
    sem = asyncio.Semaphore(4)

    async def once():
        async with sem:
            pass

    asyncio.run(once())
    asyncio.run(once())  # 不抛，所以那种写法作为回归测试是无效的
