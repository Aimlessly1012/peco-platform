"""嵌入输入截断（M4 验收现场修复）：超长文本按 embedding_max_chars 截断后送 API。"""
from unittest.mock import AsyncMock

from app.core.config import settings
from app.services.ingest.embedder import Embedder


async def test_embed_batch_truncates_long_text(monkeypatch):
    embedder = Embedder()
    captured: dict = {}

    async def fake_create(**kwargs):
        captured["input"] = kwargs["input"]

        class Item:
            embedding = [0.0] * settings.embedding_dim

        class Resp:
            data = [Item() for _ in kwargs["input"]]

        return Resp()

    fake_client = AsyncMock()
    fake_client.embeddings.create = fake_create
    monkeypatch.setattr(Embedder, "client", property(lambda self: fake_client))

    long_text = "中" * (settings.embedding_max_chars * 2)
    short_text = "def foo(): pass"
    await embedder._embed_batch([long_text, short_text])

    assert len(captured["input"][0]) == settings.embedding_max_chars
    assert captured["input"][1] == short_text  # 短文本原样
