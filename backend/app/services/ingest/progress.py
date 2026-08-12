"""阶段内子进度（M4 D6）：把 (done,total) 线性映射到进度区间并节流写库。

大仓库的 summarize/embed 会跑十几分钟，没有子进度时 progress 长时间停在阶段起点，
用户无法判断是在跑还是卡死。节流避免千文件级仓库把库写爆（每 5% 或 ≥2 秒一次）。
"""
import time

THROTTLE_PCT = 5
THROTTLE_SECONDS = 2.0


class StageProgress:
    """一个阶段的子进度上报器。作为 async 回调传给 summarize/embed 循环。

    writer(progress:int, stats:dict) 由调用方注入（pipeline 传写库函数，测试传假函数）。
    """

    def __init__(
        self,
        stats: dict,
        *,
        start: int,
        end: int,
        key: str,
        writer,
        throttle_pct: int = THROTTLE_PCT,
        throttle_seconds: float = THROTTLE_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self.stats = stats
        self.start = start
        self.end = end
        self.key = key
        self._writer = writer
        self._throttle_pct = throttle_pct
        self._throttle_seconds = throttle_seconds
        self._clock = clock
        self._last_pct = start
        self._last_at: float | None = None
        self.writes = 0

    def percent(self, done: int, total: int) -> int:
        if total <= 0:
            return self.start
        ratio = min(max(done / total, 0.0), 1.0)
        return self.start + int((self.end - self.start) * ratio)

    async def __call__(self, done: int, total: int) -> None:
        self.stats[f"{self.key}_done"] = done
        self.stats[f"{self.key}_total"] = total
        pct = self.percent(done, total)
        now = self._clock()
        finished = total > 0 and done >= total
        elapsed = None if self._last_at is None else now - self._last_at
        should_write = (
            finished
            or self._last_at is None
            or pct - self._last_pct >= self._throttle_pct
            or elapsed >= self._throttle_seconds
        )
        if not should_write:
            return
        self._last_pct = pct
        self._last_at = now
        self.writes += 1
        # 下划线开头是管道内部键（如 _module_hashes），不进 stats_json
        await self._writer(
            pct, {k: v for k, v in self.stats.items() if not k.startswith("_")}
        )


class BatchCounter:
    """把多次 embed_texts 调用的批进度累加成一条全局进度（embed 阶段分三批调用）。"""

    def __init__(self, report, total_batches: int) -> None:
        self._report = report
        self._total = total_batches
        self._done = 0

    def phase(self):
        """返回本次 embed_texts 用的回调；本次完成数叠加在此前累计值之上。"""
        base = self._done

        async def on_progress(done: int, total: int) -> None:
            self._done = base + done
            await self._report(self._done, self._total)

        return on_progress


def batch_count(item_count: int, batch_size: int) -> int:
    if item_count <= 0 or batch_size <= 0:
        return 0
    return (item_count + batch_size - 1) // batch_size
