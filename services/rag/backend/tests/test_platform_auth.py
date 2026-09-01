"""平台 GitHub 登录态（M12 B1/B2）。

重点：
1. JWS 验签的成功/失败/过期
2. status 非 approved、本地被禁用都要挡住
3. AUTH_JWT_SECRET 为空时行为完全回到 M8（迁移期退路）
4. MCP 端点绝不受影响——它走独立 MCP_AUTH_TOKEN（M7 踩过 root_path 绕过的坑）
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.tables import User, UserRole
from app.services.auth.platform import decode_platform_token, is_approved

PLATFORM_SECRET = "platform-shared-secret-at-least-32-bytes!!"
COOKIE = "next-auth.session-token"


@pytest.fixture
def platform_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", PLATFORM_SECRET)
    monkeypatch.setattr(settings, "platform_cookie_name", COOKIE)


@pytest.fixture
def platform_off(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", "")


def platform_token(
    github_id="12345", role="member", status="approved", name="Peco",
    secret=PLATFORM_SECRET, ttl_hours=24, **extra,
):
    now = datetime.now(timezone.utc)
    payload = {
        "github_id": github_id, "role": role, "status": status, "name": name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
        **extra,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------- 验签 ----------------


def test_decode_valid_token(platform_on):
    claims = decode_platform_token(platform_token())

    assert claims["github_id"] == "12345"
    assert claims["role"] == "member"
    assert claims["status"] == "approved"
    assert claims["name"] == "Peco"
    assert is_approved(claims)


def test_decode_rejects_wrong_secret(platform_on):
    """别人用自己的密钥签的 token 不能进来。"""
    assert decode_platform_token(platform_token(secret="attacker-secret")) is None


def test_decode_rejects_expired(platform_on):
    assert decode_platform_token(platform_token(ttl_hours=-1)) is None


def test_decode_rejects_tampered(platform_on):
    token = platform_token()
    header, payload, sig = token.split(".")
    assert decode_platform_token(f"{header}.{payload}x.{sig}") is None
    assert decode_platform_token(token[:-4] + "AAAA") is None


@pytest.mark.parametrize("bad", ["", "not.a.token", "a.b.c"])
def test_decode_rejects_malformed(platform_on, bad):
    assert decode_platform_token(bad) is None


def test_decode_disabled_when_secret_empty(platform_off):
    """spec: AUTH_JWT_SECRET 为空 = 整条平台路径关闭。"""
    assert decode_platform_token(platform_token()) is None


def test_decode_requires_github_id(platform_on):
    """没有 github_id 就没法映射到 RAG 用户，只能拒。"""
    token = jwt.encode(
        {"role": "member", "status": "approved", "exp": 9999999999},
        PLATFORM_SECRET, algorithm="HS256",
    )
    assert decode_platform_token(token) is None


def test_decode_requires_status(platform_on):
    """status 缺失按未批准处理——字段名对不上时宁可全拒，不能默认放行。"""
    token = jwt.encode(
        {"github_id": "1", "role": "member", "exp": 9999999999},
        PLATFORM_SECRET, algorithm="HS256",
    )
    assert decode_platform_token(token) is None


@pytest.mark.parametrize("key", ["github_id", "githubId"])
def test_decode_accepts_field_name_variants(platform_on, key):
    """平台侧 jwt 回调的字段命名不确定，认宽一点比上线后对不上强。"""
    token = jwt.encode(
        {key: "999", "status": "approved", "exp": 9999999999},
        PLATFORM_SECRET, algorithm="HS256",
    )
    assert decode_platform_token(token)["github_id"] == "999"


def test_role_defaults_to_member(platform_on):
    token = jwt.encode(
        {"github_id": "1", "status": "approved", "exp": 9999999999},
        PLATFORM_SECRET, algorithm="HS256",
    )
    assert decode_platform_token(token)["role"] == "member"


@pytest.mark.parametrize("status", ["pending", "rejected", "banned", ""])
def test_is_approved_only_for_approved(status):
    assert is_approved({"status": status}) is False


def test_disabled_user_rejected_even_when_approved():
    """PM 验收回归：平台禁用用户时只写 disabled_at、不改 status。

    只看 status 的话，管理员在平台点的「禁用」对 RAG 完全无效——实测放行了全部项目数据。
    平台禁用与 RAG 本地 disabled_at 是并集关系：任一侧禁用都必须拒绝。
    """
    assert is_approved({"status": "approved", "disabled": True}) is False
    assert is_approved({"status": "approved", "disabled": False}) is True
    assert is_approved({"status": "approved"}) is True  # 老 token 没这个字段，不影响


def test_decode_carries_disabled_flag(platform_on):
    """disabled 必须从 token 里解出来，否则守卫无从判断。"""
    assert decode_platform_token(platform_token(disabled=True))["disabled"] is True
    assert decode_platform_token(platform_token())["disabled"] is False


# ---------------- 端到端守卫 ----------------


async def get_user_by_github(test_db, github_id) -> User | None:
    async with test_db() as session:
        return await session.scalar(
            select(User).where(User.github_id == github_id)
        )


async def test_platform_token_grants_access(anon_client, test_db, platform_on):
    anon_client.cookies.set(COOKIE, platform_token(github_id="777", name="Alice"))

    resp = await anon_client.get("/auth/me")

    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


async def test_first_visit_creates_local_user(anon_client, test_db, platform_on):
    """B2：首次见到某 github_id 时在 RAG 侧建档（chat_sessions 外键才有得指）。"""
    assert await get_user_by_github(test_db, "888") is None
    anon_client.cookies.set(COOKIE, platform_token(github_id="888", name="Bob"))

    await anon_client.get("/auth/me")

    user = await get_user_by_github(test_db, "888")
    assert user is not None
    assert user.role == UserRole.MEMBER


async def test_repeat_visits_reuse_same_user(anon_client, test_db, platform_on):
    """第二次请求不能再建一条——否则会话归属会散在多个用户上。"""
    anon_client.cookies.set(COOKIE, platform_token(github_id="999"))

    await anon_client.get("/auth/me")
    await anon_client.get("/auth/me")

    async with test_db() as session:
        rows = list(await session.scalars(
            select(User).where(User.github_id == "999")
        ))
    assert len(rows) == 1


async def test_role_follows_platform(anon_client, test_db, platform_on):
    """平台是角色的权威来源：升为 admin 后立即能进管理接口。"""
    anon_client.cookies.set(COOKIE, platform_token(github_id="555", role="member"))
    assert (await anon_client.get("/auth/users")).status_code == 403

    anon_client.cookies.set(COOKIE, platform_token(github_id="555", role="admin"))
    assert (await anon_client.get("/auth/users")).status_code == 200

    user = await get_user_by_github(test_db, "555")
    assert user.role == UserRole.ADMIN


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_unapproved_user_blocked(anon_client, test_db, platform_on, status):
    """spec: 未批准用户被挡，且不告诉他"你的状态是 pending"。"""
    anon_client.cookies.set(COOKIE, platform_token(github_id="666", status=status))

    resp = await anon_client.get("/projects")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "请先登录"
    assert await get_user_by_github(test_db, "666") is None   # 未批准不建档


async def test_locally_disabled_user_blocked(anon_client, test_db, platform_on):
    """M11 的本地禁用对平台登录态同样有效（管理接口不能因为换了登录方式就失效）。"""
    anon_client.cookies.set(COOKIE, platform_token(github_id="444"))
    assert (await anon_client.get("/auth/me")).status_code == 200

    async with test_db() as session:
        user = await session.scalar(select(User).where(User.github_id == "444"))
        user.disabled_at = datetime.now(timezone.utc)
        await session.commit()

    assert (await anon_client.get("/auth/me")).status_code == 401



async def test_invalid_platform_token_is_rejected(anon_client, test_db, platform_on):
    """平台 cookie 无效即 401。

    迁移期这里曾回落到密码登录；M12 阶段三密码登录已删除，坏 token 不再有任何兜底
    ——留着一条无人能签发的验证分支，等于给拿到 SECRET_KEY 的人留了伪造登录态的门。
    """
    anon_client.cookies.set(COOKIE, "garbage-token")

    assert (await anon_client.get("/projects")).status_code == 401
    assert (await anon_client.get("/auth/me")).status_code == 401

async def test_platform_cookie_ignored_when_disabled(
    anon_client, test_db, platform_off
):
    """关闭态下平台 cookie 一律无效，不会有"半开"的中间状态。"""
    anon_client.cookies.set(COOKIE, platform_token())
    assert (await anon_client.get("/auth/me")).status_code == 401


async def test_chat_session_belongs_to_platform_user(
    anon_client, test_db, platform_on
):
    """B2 的落点：平台用户建的会话要挂在建档出来的 users.id 上。"""
    from app.models.tables import ChatSession, Project, ProjectStatus

    async with test_db() as session:
        project = Project(name="p", git_url="https://x.git", status=ProjectStatus.READY)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        pid = project.id

    anon_client.cookies.set(COOKIE, platform_token(github_id="333"))
    created = await anon_client.post(f"/projects/{pid}/sessions", json={"title": "t"})

    assert created.status_code == 201
    user = await get_user_by_github(test_db, "333")
    async with test_db() as session:
        chat = await session.get(ChatSession, uuid.UUID(created.json()["id"]))
    assert chat.user_id == user.id


# ---------------- MCP 不受影响（M7 事故回归） ----------------


async def test_mcp_unaffected_by_platform_auth(anon_client, platform_on):
    """spec: MCP 走独立 MCP_AUTH_TOKEN，与账号体系无关。

    这里断言的是"没有平台 cookie 也不会被账号守卫拦"——MCP 是 ASGI mount 的子应用，
    账号守卫是路由级依赖伸不进去，但这条测试防的是有人日后改成全局中间件。
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    try:
        resp = await anon_client.post("/mcp", json=body, headers=headers)
    except RuntimeError as e:
        # 该 fixture 不进 lifespan，session manager 没起——能抛到这里说明
        # 请求已经进了 MCP 子应用，而不是被账号守卫挡在门外
        assert "Task group" in str(e)
    else:
        assert resp.status_code != 401


async def test_mcp_bearer_guard_still_works(test_db, monkeypatch, platform_on):
    """带/不带 MCP_AUTH_TOKEN 的行为不因平台鉴权改动而变（M7 回归）。"""
    from app.mcp_server.auth import MCPAuthMiddleware

    reached = {}

    async def inner(scope, receive, send):
        reached["yes"] = True

    mw = MCPAuthMiddleware(inner, token="mcp-secret", path="/mcp")
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request"}

    # 无 token → 401（平台 cookie 帮不上忙，两套体系互不相干）
    await mw({"type": "http", "path": "/mcp", "headers": [
        (b"cookie", f"{COOKIE}={platform_token()}".encode())
    ]}, receive, send)
    assert "yes" not in reached
    assert sent[0]["status"] == 401

    # 带对 token → 放行
    await mw({"type": "http", "path": "/mcp", "headers": [
        (b"authorization", b"Bearer mcp-secret")
    ]}, receive, send)
    assert reached.get("yes") is True
