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


@pytest.fixture
def fake_summarizer(monkeypatch):
    """确定性假摘要：文本含路径/模块名关键词，使词袋假向量可命中摘要层。"""
    from app.services.ingest import summarizer as sm

    async def summarize_file(self, path, imports, chunks, head):
        symbols = " ".join(c.symbol for c in chunks[:5])
        return f"负责 {path} 的实现，包含 {symbols}"

    async def summarize_module(self, name, kind, prefix, entries, file_summaries):
        return f"{name} 模块（{kind}）：负责 {name} 相关业务流程，入口 {prefix}"

    async def summarize_project(self, readme, module_map, module_summaries):
        names = ", ".join(module_summaries)
        return f"Mini Shop 全栈演示项目，功能模块：{names}"

    monkeypatch.setattr(type(sm.summarizer), "summarize_file", summarize_file)
    monkeypatch.setattr(type(sm.summarizer), "summarize_module", summarize_module)
    monkeypatch.setattr(type(sm.summarizer), "summarize_project", summarize_project)
    return sm.summarizer
