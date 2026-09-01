"""测试公共设施：环境护栏、确定性假嵌入、sqlite 临时库与 API 客户端。

**本文件最上面那段护栏（_isolate_settings）必须留在模块顶层、且在任何 app 模块被
导入之前执行**——它是"从仓库根误跑 pytest 会加载真实 .env 打计费接口"这个真风险
的唯一屏障（M17 D6）。往下加代码时不要把它挪到 fixture 里。
"""
import hashlib
import math
import re
import socket
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, settings

# ---------------- 环境护栏（M17 1.2 / D6）----------------

DUMMY_API_KEY = "test-dummy-key-not-a-real-credential"
# 打不通的地址：万一有代码真去调，立刻连接失败，而不是打到计费接口上
DEAD_BASE_URL = "http://127.0.0.1:1/v1"


def _isolate_settings() -> None:
    """把进程内的 settings 单例换成"不读任何 .env"的版本，并钉死凭据。

    为什么是就地改而不是重新赋值：settings 被十几个模块 `from ... import settings`
    绑到了各自的命名空间，重新赋值只会换掉本模块这一个引用。

    为什么要有这一层：pydantic-settings 的 env_file 是相对 **CWD** 解析的。
    在 backend/ 下跑没事（那儿没有 .env），但在仓库根跑就会加载根 .env——里面是
    真的 API key，测试一旦漏打就是真金白银 + 真实模型的不确定输出。
    """
    clean = Settings(_env_file=None)
    for name in type(settings).model_fields:
        object.__setattr__(settings, name, getattr(clean, name))

    # 环境变量优先级高于 env_file，clean 也可能捡到 shell 里 export 的真 key，
    # 所以凭据一律显式盖成哑值
    settings.embedding_api_key = DUMMY_API_KEY
    settings.chat_api_key = DUMMY_API_KEY
    settings.embedding_base_url = DEAD_BASE_URL
    settings.chat_base_url = DEAD_BASE_URL
    # rerank 三项留空 = 关闭。这是默认态，测试全都建立在它之上；
    # 给个哑值反而会把 rerank_enabled 变成 True，整片行为跟着变
    settings.rerank_base_url = ""
    settings.rerank_api_key = ""
    settings.rerank_model = ""
    # 对象存储默认关闭：绝大多数用例假设 storage_enabled() 为 False，
    # 要用的用例（bundle 演练）自己打开
    settings.minio_access_key = ""
    settings.minio_secret_key = ""
    settings.mcp_auth_token = ""
    settings.admin_password = ""


_isolate_settings()


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

    # M15：检索侧改走 LangChain Embeddings 组件（vector_store.retrieval_embeddings），
    # 同一份确定性假向量必须也覆盖到它——否则集成测试会真的去打嵌入 API。
    # 打在组件工厂上而不是 embed_query 函数上：service 是 from-import 绑定的，
    # 补在工厂这层无论谁引用都生效。
    class FakeEmbeddings:
        def embed_query(self, text):
            return fake_embed(text)

        def embed_documents(self, texts):
            return [fake_embed(t) for t in texts]

        async def aembed_query(self, text):
            return fake_embed(text)

        async def aembed_documents(self, texts):
            return [fake_embed(t) for t in texts]

    monkeypatch.setattr(
        "app.services.retrieval.vector_store.retrieval_embeddings",
        lambda: FakeEmbeddings(),
    )
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
    "app.services.ingest.celery_tasks",  # M13 幂等门要查 index_jobs 表
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


PLATFORM_TEST_SECRET = "conftest-platform-secret-at-least-32-chars!"


@pytest.fixture(autouse=True)
def _platform_auth_on(monkeypatch):
    """测试默认启用平台鉴权：M12 阶段三后它是唯一的登录态来源。

    要测「没配密钥」的场景，用例里自行 monkeypatch 成空串即可。
    """
    monkeypatch.setattr(settings, "auth_jwt_secret", PLATFORM_TEST_SECRET)


async def seed_user(session_factory, username: str, role: str):
    """建一个用户并返回 (user_id, 平台登录态 cookie)。

    M12 阶段三起密码登录已删除，登录态一律来自平台的 GitHub 会话——这里签一个
    与平台 NextAuth 同格式的 JWS(HS256)，走的是真实验签路径，不 mock 依赖。
    """
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings
    from app.models.tables import User

    github_id = f"gh-{username}"
    async with session_factory() as session:
        user = User(username=username, github_id=github_id, role=role)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id

    now = datetime.now(timezone.utc)
    token = pyjwt.encode(
        {
            "githubId": github_id,
            "name": username,
            "role": role,
            "status": "approved",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=12)).timestamp()),
        },
        settings.auth_jwt_secret or PLATFORM_TEST_SECRET,
        algorithm="HS256",
    )
    return uid, {settings.platform_cookie_name: token}


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


# ---------------- 集成档：超时放宽、放行本机网络、依赖不可达就 skip ----------------

INTEGRATION_TIMEOUT = 300
NEO4J_DEFAULT_BOLT = ("localhost", 7687)
MINIO_ENV = "MINIO_TEST_ENDPOINT"
_reachable_cache: dict[tuple[str, int], bool] = {}


def pytest_collection_modifyitems(items):
    """集成用例放宽超时：起容器 + 建图本来就比单测慢一个量级。"""
    for item in items:
        if item.get_closest_marker("integration") and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(INTEGRATION_TIMEOUT))


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """端口可连通性探测，结果按 (host, port) 缓存——一轮测试里没必要反复探。"""
    key = (host, port)
    if key not in _reachable_cache:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                _reachable_cache[key] = True
        except OSError:
            _reachable_cache[key] = False
    return _reachable_cache[key]


def _bolt_target() -> tuple[str, int]:
    from urllib.parse import urlparse

    parsed = urlparse(settings.neo4j_uri)
    return parsed.hostname or NEO4J_DEFAULT_BOLT[0], parsed.port or NEO4J_DEFAULT_BOLT[1]


@pytest.fixture(autouse=True)
def _integration_environment(request):
    """集成用例的统一前置：放行本机网络 + 依赖不可达时 skip 而不是报连接错。

    以前 Neo4j 没起时整片集成用例以 ServiceUnavailable 失败，看起来像"代码坏了"；
    skip 带原因才是诚实的信号（spec: 依赖不可达 SHALL skip 并说明原因）。
    """
    if request.node.get_closest_marker("integration") is None:
        return
    import pytest_socket

    pytest_socket.enable_socket()      # design D6：集成档不启用禁网
    host, port = _bolt_target()
    if not port_open(host, port):
        pytest.skip(f"Neo4j 不可达（bolt://{host}:{port}）：先 docker compose up -d neo4j")


@pytest.fixture
def require_minio():
    """需要真 MinIO 的用例用它；不可达就 skip，并返回 (endpoint, access, secret)。"""
    import os

    endpoint = os.environ.get(MINIO_ENV, "localhost:9000")
    host, _, port = endpoint.partition(":")
    if not port_open(host, int(port or 9000)):
        pytest.skip(
            f"MinIO 不可达（{endpoint}）：设 {MINIO_ENV} 或 docker compose up -d minio"
        )
    return endpoint, os.environ.get("MINIO_TEST_ACCESS_KEY", "ragminio"), os.environ.get(
        "MINIO_TEST_SECRET_KEY", "ragminio123"
    )


# ---------------- bundle 演练共用夹具（M17 组 4） ----------------


@pytest.fixture
def origin(tmp_path):
    """两个提交的"远端"仓库。"""
    from types import SimpleNamespace

    from git import Repo

    from tests.helpers.repos import init_repo_with, write_and_commit

    path = tmp_path / "origin"
    first = init_repo_with(path, {"a.py": "def a():\n    return 1\n"})
    repo = Repo(path)
    second = write_and_commit(repo, path, {"b.py": "def b():\n    return 2\n"}, "second")
    return SimpleNamespace(path=path, url=str(path), repo=repo,
                           first=first, head=second)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """目录当 MinIO：能装 bundle，也能造「缺失/损坏/抛异常」三种故障。"""
    from types import SimpleNamespace

    from app.services.ingest import git_ops

    root = tmp_path / "minio"
    root.mkdir()
    state = {"enabled": True, "download_raises": False, "upload_raises": False,
             "uploaded": []}

    def storage_enabled():
        return state["enabled"]

    def download_file(key, dest):
        if state["download_raises"]:
            raise OSError("minio 不可达")
        src = root / key.replace("/", "_")
        if not src.exists():
            return False
        Path(dest).write_bytes(src.read_bytes())
        return True

    def upload_file(key, path, content_type=None):
        if state["upload_raises"]:
            raise OSError("minio 不可达")
        (root / key.replace("/", "_")).write_bytes(Path(path).read_bytes())
        state["uploaded"].append((key, content_type))
        return key

    monkeypatch.setattr(git_ops, "minio_client", SimpleNamespace(
        storage_enabled=storage_enabled, download_file=download_file,
        upload_file=upload_file,
    ))
    state["root"] = root
    state["path_of"] = lambda key: root / key.replace("/", "_")
    return state
