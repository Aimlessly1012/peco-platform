"""测试公共设施：确定性假嵌入（词袋向量），使检索冒烟无需真实 API。"""
import hashlib
import math
import re

import pytest

from app.core.config import settings


def fake_embed(text: str) -> list[float]:
    """词袋式确定性向量：共享标识符的文本 cosine 相似度更高。"""
    dim = settings.embedding_dim
    vec = [0.0] * dim
    words = re.findall(r"[a-zA-Z_一-鿿]+", text.lower())
    tokens: list[str] = []
    for w in words:
        tokens.append(w)
        tokens.extend(p for p in w.split("_") if p)  # snake_case 拆分
    for token in tokens:
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def fake_embedder(monkeypatch):
    from app.services.ingest import embedder as embedder_module

    async def embed_texts(self, texts):
        return [fake_embed(t) for t in texts]

    async def embed_query(self, text):
        return fake_embed(text)

    monkeypatch.setattr(type(embedder_module.embedder), "embed_texts", embed_texts)
    monkeypatch.setattr(type(embedder_module.embedder), "embed_query", embed_query)
    return embedder_module.embedder
