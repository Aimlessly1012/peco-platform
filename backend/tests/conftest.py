"""测试公共设施：确定性假嵌入（词袋向量），使检索冒烟无需真实 API；sqlite 内存库与 API 客户端。"""
import hashlib
import math
import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
    "app.services.auth.bootstrap",   # M8 管理员初始化在 lifespan 里查 users 表
)


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    """sqlite 临时文件库 + 开 FK 校验，覆盖各模块的 SessionLocal。

    不用内存库 + StaticPool：共享单连接会让并发请求的事务互相污染
    （A commit 把 B 未回滚的 flush 一起带上库），且 SQLite 默认不查外键——
    这两点曾把生产 Postgres 上的真 bug（注册 FK 顺序、并发回滚）藏成绿灯。
    文件库多连接各自独立事务，写锁等待语义与 Postgres 行锁接近。
    """
    import importlib

    from sqlalchemy import event

    from app.models.tables import Base

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        connect_args={"timeout": 30},  # 并发写撞库级锁时等待而不是立刻 SQLITE_BUSY
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    for name in _SESSION_LOCAL_USERS:
        importlib.import_module(name)
        monkeypatch.setattr(f"{name}.SessionLocal", session_factory, raising=False)
    yield session_factory
    await engine.dispose()


async def seed_user(session_factory, username: str, role: str):
    """建一个用户并返回 (user_id, 登录 cookie)。走真实 JWT，不 mock 依赖。"""
    from app.models.tables import User
    from app.services.auth.security import COOKIE_NAME, create_token, hash_password

    async with session_factory() as session:
        user = User(
            username=username, password_hash=hash_password("pw123456"), role=role
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id, {COOKIE_NAME: create_token(str(user.id), role)}


@pytest.fixture
async def api_client(test_db):
    """不进 lifespan 的 API 客户端（避免测试依赖 Neo4j 启动检查）。

    M8 起默认带 admin 登录态——业务测试关心的是业务行为，鉴权本身由
    test_auth.py 专门覆盖。要测未登录/member 的场景请用 anon_client / member_client。
    """
    from app.core.db import get_session
    from app.main import app
    from app.models.tables import UserRole

    async def override_session():
        async with test_db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    _, cookies = await seed_user(test_db, "admin", UserRole.ADMIN)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8001", cookies=cookies
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def anon_client(test_db):
    """无登录态客户端（测守卫用）。"""
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


@pytest.fixture
async def member_client(test_db):
    """member 登录态客户端（测权限边界用）。"""
    from app.core.db import get_session
    from app.main import app
    from app.models.tables import UserRole

    async def override_session():
        async with test_db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    user_id, cookies = await seed_user(test_db, "member1", UserRole.MEMBER)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8001", cookies=cookies
    ) as client:
        client.user_id = user_id
        yield client
    app.dependency_overrides.clear()
