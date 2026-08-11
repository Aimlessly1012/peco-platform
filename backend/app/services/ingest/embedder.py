"""DashScope text-embedding-v3 嵌入客户端（OpenAI 兼容）：批量、并发上限、指数退避。"""
import asyncio
import logging

from openai import APIError, AsyncOpenAI, RateLimitError

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
            )
        return self._client

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        delay = 2.0
        for attempt in range(4):
            try:
                async with self._semaphore:
                    resp = await self.client.embeddings.create(
                        model=settings.embedding_model,
                        input=texts,
                        dimensions=settings.embedding_dim,
                    )
                return [d.embedding for d in resp.data]
            except (RateLimitError, APIError, TimeoutError) as e:
                if attempt == 3:
                    raise
                logger.warning("嵌入调用失败（%s），%.0fs 后重试", type(e).__name__, delay)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """按批大小切分并发嵌入，保持输入顺序。"""
        batch_size = settings.embedding_batch_size
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vec for batch in results for vec in batch]

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([text]))[0]


embedder = Embedder()
