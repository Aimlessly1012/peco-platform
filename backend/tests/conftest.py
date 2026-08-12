"""测试公共设施：确定性假嵌入（词袋向量），使检索冒烟无需真实 API；sqlite 内存库与 API 客户端。"""
import hashlib
import math
import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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

    async def embed_texts(self, texts, on_progress=None):
        if on_progress is not None:  # 与真实签名一致（M4 子进度）
            total = max(1, math.ceil(len(texts) / settings.embedding_batch_size))
            for done in range(1, total + 1):
                await on_progress(done, total)
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


# SessionLocal 被各模块 `from app.core.db import SessionLocal` 绑到自己的命名空间，
# 换库时每处都要替换（漏一处测试就会连到真实 Postgres）。
_SESSION_LOCAL_USERS = (
    "app.core.db",
    "app.main",
    "app.services.report.service",
    "app.services.ingest.pipeline",
    "app.mcp_server.resolver",
    "app.mcp_server.server",
    "app.api.chat",
)


@pytest.fixture
async def test_db(monkeypatch):
    """sqlite 内存库（StaticPool 使多连接共享同一库）+ 覆盖各模块的 SessionLocal。"""
    import importlib

    from app.models.tables import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    for name in _SESSION_LOCAL_USERS:
        importlib.import_module(name)
        monkeypatch.setattr(f"{name}.SessionLocal", session_factory, raising=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
async def api_client(test_db):
    """不进 lifespan 的 API 客户端（避免测试依赖 Neo4j 启动检查）。"""
    from app.core.db import get_session
    from app.main import app

    async def override_session():
        async with test_db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8001") as client:
        yield client
    app.dependency_overrides.clear()
