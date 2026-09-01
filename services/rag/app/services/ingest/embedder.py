"""DashScope text-embedding-v3 嵌入客户端（OpenAI 兼容）：批量、并发上限、指数退避。"""
import asyncio
import logging

from openai import APIError, AsyncOpenAI, BadRequestError, RateLimitError

from app.core.config import settings

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._semaphore = asyncio.Semaphore(settings.embedding_concurrency)

    @property
    def client(self) -> AsyncOpenAI:
        # 惰性初始化：导入时不要求 api_key（测试 mock / 未配置时启动不崩）
        if self._client is None:
            if not settings.embedding_api_key:
                raise RuntimeError("未配置 EMBEDDING_API_KEY，无法调用嵌入服务")
            self._client = AsyncOpenAI(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key,
                timeout=settings.embedding_timeout_seconds,  # M4 D7：超时进入既有退避
            )
        return self._client

    async def _embed_once(self, texts: list[str]) -> list[list[float]]:
        async with self._semaphore:
            resp = await self.client.embeddings.create(
                model=settings.embedding_model,
                input=texts,
                dimensions=settings.embedding_dim,
            )
        return [d.embedding for d in resp.data]

    async def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """一批嵌入。可重试错误退避重试；400 类（如超 token 上限的 emoji 密集文本、
        空文本）降级逐条定位，坏条返回 None（跳过向量，节点仍入图）——单条坏文本
        不炸整个索引（错误哲学）。"""
        # 统一按模型输入上限截断（如 text-embedding-v2 仅 2048 token）。
        # 缓存键 embed_key 按截断前全文计算：同全文 → 同截断 → 同向量，确定性不受影响
        limit = settings.embedding_max_chars
        texts = [t[:limit] if t.strip() else " " for t in texts]
        delay = 2.0
        for attempt in range(4):
            try:
                return await self._embed_once(texts)  # type: ignore[return-value]
            except BadRequestError:
                # 输入内容本身非法（长度/字符），重试无意义 → 逐条定位坏文本
                logger.warning("嵌入批次 400，降级逐条定位坏文本（batch=%d）", len(texts))
                results: list[list[float] | None] = []
                for t in texts:
                    try:
                        results.append((await self._embed_once([t]))[0])
                    except BadRequestError:
                        # 再砍半长度救一次（token 密集字符场景），仍失败则放弃该条
                        try:
                            results.append((await self._embed_once([t[: limit // 2]]))[0])
                        except BadRequestError:
                            logger.warning("单条文本无法嵌入，跳过向量（前 80 字符：%r）", t[:80])
                            results.append(None)
                return results
            except (RateLimitError, APIError, TimeoutError) as e:
                if attempt == 3:
                    raise
                logger.warning("嵌入调用失败（%s），%.0fs 后重试", type(e).__name__, delay)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    async def embed_texts(self, texts: list[str], on_progress=None) -> list[list[float]]:
        """按批大小切分并发嵌入，保持输入顺序。

        on_progress(done, total) 在每批完成时回调（批数口径，M4 D6 子进度）。
        """
        batch_size = settings.embedding_batch_size
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        if on_progress is None:
            results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
            return [vec for batch in results for vec in batch]

        total = len(batches)
        done = 0

        async def run(index: int, batch: list[str]):
            nonlocal done
            vectors = await self._embed_batch(batch)
            done += 1
            await on_progress(done, total)
            return index, vectors

        completed = await asyncio.gather(
            *(run(i, b) for i, b in enumerate(batches))
        )
        ordered = [vectors for _, vectors in sorted(completed, key=lambda x: x[0])]
        return [vec for batch in ordered for vec in batch]

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([text]))[0]


embedder = Embedder()
