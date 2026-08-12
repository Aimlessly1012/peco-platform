"""阶段内子进度单测（M4 B1）：区间映射、节流规则、跨调用批次累计。"""
import pytest

from app.services.ingest.progress import BatchCounter, StageProgress, batch_count


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_reporter(stats=None, clock=None, **kwargs):
    writes: list[tuple[int, dict]] = []

    async def writer(pct: int, snapshot: dict) -> None:
        writes.append((pct, snapshot))

    reporter = StageProgress(
        stats if stats is not None else {},
        start=25, end=55, key="summarize", writer=writer,
        clock=clock or FakeClock(), **kwargs,
    )
    return reporter, writes


def test_percent_maps_into_range():
    reporter, _ = make_reporter()
    assert reporter.percent(0, 100) == 25
    assert reporter.percent(50, 100) == 40
    assert reporter.percent(100, 100) == 55
    assert reporter.percent(0, 0) == 25       # 空阶段不除零
    assert reporter.percent(200, 100) == 55   # 越界被夹住


async def test_first_and_last_always_written():
    clock = FakeClock()
    reporter, writes = make_reporter(clock=clock)

    await reporter(1, 100)     # 首次必写
    await reporter(2, 100)     # 距上次 <5% 且 <2s → 跳过
    await reporter(100, 100)   # 末次必写

    assert [pct for pct, _ in writes] == [25, 55]


async def test_throttled_by_percent_step():
    clock = FakeClock()
    reporter, writes = make_reporter(clock=clock)

    for done in range(0, 101, 2):
        await reporter(done, 100)

    # 30 个百分点跨度、每 5 个点一写 → 远少于 51 次调用
    assert 5 <= len(writes) <= 10
    assert writes[-1][0] == 55


async def test_throttled_by_elapsed_time():
    clock = FakeClock()
    reporter, writes = make_reporter(clock=clock)

    await reporter(0, 10_000)        # 首次
    await reporter(1, 10_000)        # 同一时刻、进度几乎没动 → 跳过
    assert len(writes) == 1

    clock.advance(2.5)               # 超过 2s 阈值 → 即使进度没动也写一次（证明还活着）
    await reporter(2, 10_000)
    assert len(writes) == 2


async def test_stats_keys_and_private_filter():
    stats = {"files_parsed": 3, "_module_hashes": {"a": "b"}}
    reporter, writes = make_reporter(stats=stats)

    await reporter(7, 20)

    assert stats["summarize_done"] == 7
    assert stats["summarize_total"] == 20
    snapshot = writes[0][1]
    assert snapshot["summarize_done"] == 7
    assert snapshot["files_parsed"] == 3
    assert "_module_hashes" not in snapshot  # 内部键不落 stats_json


async def test_batch_counter_accumulates_across_calls():
    """embed 阶段分三次调用 embed_texts，进度必须连续而不是各自从 0 开始。"""
    seen: list[tuple[int, int]] = []

    async def report(done: int, total: int) -> None:
        seen.append((done, total))

    counter = BatchCounter(report, total_batches=6)

    first = counter.phase()
    await first(1, 3)
    await first(3, 3)

    second = counter.phase()
    await second(1, 2)
    await second(2, 2)

    third = counter.phase()
    await third(1, 1)

    assert seen == [(1, 6), (3, 6), (4, 6), (5, 6), (6, 6)]


@pytest.mark.parametrize(
    "count,size,expect", [(0, 10, 0), (1, 10, 1), (10, 10, 1), (11, 10, 2), (25, 10, 3)]
)
def test_batch_count(count, size, expect):
    assert batch_count(count, size) == expect


async def test_embedder_keeps_order_when_batches_finish_out_of_order(monkeypatch):
    """带回调的分批嵌入必须保持输入顺序——后发批次先完成时也不能错位。"""
    import asyncio

    from app.core.config import settings
    from app.services.ingest.embedder import Embedder

    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    embedder = Embedder()
    calls: list[tuple[int, int]] = []

    async def fake_batch(self, texts):
        # 让靠后的批先返回：第一批睡最久
        await asyncio.sleep(0.03 if texts[0] == "t0" else 0.001)
        return [[float(int(t[1:]))] for t in texts]

    monkeypatch.setattr(Embedder, "_embed_batch", fake_batch)

    async def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    texts = [f"t{i}" for i in range(7)]
    vectors = await embedder.embed_texts(texts, on_progress=on_progress)

    assert vectors == [[float(i)] for i in range(7)]  # 顺序未被并发打乱
    assert len(calls) == 4                            # ceil(7/2) 批
    assert calls[-1] == (4, 4)
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)  # done 单调递增


async def test_embedder_without_progress_unchanged(monkeypatch):
    """不传回调时走原路径，行为与 M3 一致。"""
    from app.core.config import settings
    from app.services.ingest.embedder import Embedder

    monkeypatch.setattr(settings, "embedding_batch_size", 3)

    async def fake_batch(self, texts):
        return [[float(int(t[1:]))] for t in texts]

    monkeypatch.setattr(Embedder, "_embed_batch", fake_batch)
    vectors = await Embedder().embed_texts([f"t{i}" for i in range(5)])
    assert vectors == [[float(i)] for i in range(5)]
