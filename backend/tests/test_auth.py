"""邀请码准入单测（M8 B2-B7）。

安全测试的重点不是"功能能用"，而是"不该能用的确实不能用"：
未登录被拦、member 越权被拒、他人会话看不见也猜不到、邀请码只能用一次。
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.tables import ChatSession, InviteCode, Project, ProjectStatus, User, UserRole
from app.services.auth.security import (
    COOKIE_NAME,
    create_token,
    decode_token,
    generate_invite_code,
    hash_password,
    verify_password,
)
from tests.conftest import seed_user


# ---------------- B2 安全基件 ----------------


def test_password_hash_roundtrip():
    h = hash_password("pw123456")
    assert h != "pw123456"                      # 不能是明文
    assert h.startswith("$2b$")                 # bcrypt 格式
    assert verify_password("pw123456", h)
    assert not verify_password("pw123457", h)


def test_password_hash_is_salted():
    """同一密码两次哈希必须不同——没盐的话拖库即彩虹表。"""
    assert hash_password("same") != hash_password("same")


@pytest.mark.parametrize("bad_hash", ["", "not-a-hash", "$2b$12$短"])
def test_verify_bad_hash_returns_false(bad_hash):
    """脏数据不该把请求炸成 500。"""
    assert verify_password("pw123456", bad_hash) is False


def test_long_password_does_not_crash():
    """bcrypt 只认前 72 字节，超长密码要么截断要么抛——不能抛。"""
    long_pw = "中" * 100
    assert verify_password(long_pw, hash_password(long_pw))


def test_token_roundtrip():
    token = create_token("user-1", UserRole.ADMIN)
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == UserRole.ADMIN
    assert payload["exp"] > payload["iat"]


def test_expired_token_rejected():
    assert decode_token(create_token("u", UserRole.MEMBER, ttl_days=-1)) is None


@pytest.mark.parametrize("bad", ["", "not.a.token", "a.b.c"])
def test_malformed_token_rejected(bad):
    assert decode_token(bad) is None


def test_tampered_token_rejected():
    """改签名或改 payload 都必须失效，否则谁都能把自己签成 admin。"""
    token = create_token("u", UserRole.MEMBER)
    assert decode_token(token[:-4] + "AAAA") is None

    header, payload, sig = token.split(".")
    assert decode_token(f"{header}.{payload}x.{sig}") is None


def test_token_signed_with_other_secret_rejected():
    import jwt

    forged = jwt.encode(
        {"sub": "u", "role": "admin", "exp": 9999999999}, "attacker-key", algorithm="HS256"
    )
    assert decode_token(forged) is None


def test_invite_code_shape():
    codes = {generate_invite_code() for _ in range(200)}
    assert len(codes) > 190                      # 基本不重复
    for code in codes:
        assert len(code) == 8
        assert code.isupper() or code.isdigit()
        assert not (set(code) & set("0O1lI"))    # 去易混字符


# ---------------- B3 管理员初始化 ----------------


async def test_admin_created_on_first_boot(test_db, monkeypatch):
    """spec 场景: 全新库 + 配了 ADMIN_PASSWORD → 创建 admin。"""
    from app.core.config import settings
    from app.services.auth.bootstrap import ensure_admin_user

    monkeypatch.setattr(settings, "admin_username", "root")
    monkeypatch.setattr(settings, "admin_password", "s3cret-pw")

    await ensure_admin_user()

    async with test_db() as session:
        admin = await session.scalar(select(User).where(User.role == UserRole.ADMIN))
    assert admin.username == "root"
    assert verify_password("s3cret-pw", admin.password_hash)


async def test_admin_not_created_without_password(test_db, monkeypatch, caplog):
    from app.core.config import settings
    from app.services.auth.bootstrap import ensure_admin_user

    monkeypatch.setattr(settings, "admin_password", "")
    await ensure_admin_user()

    async with test_db() as session:
        assert await session.scalar(select(User)) is None
    assert any("ADMIN_PASSWORD" in r.message for r in caplog.records)


async def test_existing_admin_not_overwritten(test_db, monkeypatch):
    """spec: 已有 admin 后改 env 不覆盖——否则重启会把用户改过的密码冲掉。"""
    from app.core.config import settings
    from app.services.auth.bootstrap import ensure_admin_user

    await seed_user(test_db, "admin", UserRole.ADMIN)
    monkeypatch.setattr(settings, "admin_username", "hacker")
    monkeypatch.setattr(settings, "admin_password", "new-password")

    await ensure_admin_user()

    async with test_db() as session:
        admins = list(await session.scalars(select(User).where(User.role == UserRole.ADMIN)))
    assert len(admins) == 1
    assert admins[0].username == "admin"
    assert verify_password("pw123456", admins[0].password_hash)   # 原密码未变


@pytest.mark.parametrize(
    "secret,expect",
    [("dev-secret-key", False), ("short", False), ("x" * 32, True)],
)
def test_secret_key_strength_check(monkeypatch, secret, expect):
    from app.core.config import settings
    from app.services.auth.bootstrap import check_secret_key

    monkeypatch.setattr(settings, "secret_key", secret)
    assert check_secret_key() is expect


# ---------------- B4 登录 / 注册 ----------------


async def make_invite(test_db, code="ABCD2345") -> str:
    async with test_db() as session:
        session.add(InviteCode(code=code))
        await session.commit()
    return code


async def test_login_success_sets_cookie(anon_client, test_db):
    await seed_user(test_db, "alice", UserRole.MEMBER)

    resp = await anon_client.post(
        "/auth/login", json={"username": "alice", "password": "pw123456"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"username": "alice", "role": "member"}
    cookie = resp.cookies.get(COOKIE_NAME)
    assert cookie and decode_token(cookie)["role"] == "member"


async def test_login_cookie_is_httponly_lax(anon_client, test_db):
    """httpOnly 挡 XSS 读取；SameSite=Lax 挡 CSRF。"""
    await seed_user(test_db, "alice", UserRole.MEMBER)
    resp = await anon_client.post(
        "/auth/login", json={"username": "alice", "password": "pw123456"}
    )

    raw = resp.headers["set-cookie"].lower()
    assert "httponly" in raw
    assert "samesite=lax" in raw
    assert "path=/" in raw


@pytest.mark.parametrize(
    "username,password",
    [("alice", "wrong-password"), ("nobody", "pw123456")],
)
async def test_login_failures_share_one_message(anon_client, test_db, username, password):
    """spec 场景: 用户名不存在与密码错误必须同一句——否则送人一个用户名枚举接口。"""
    await seed_user(test_db, "alice", UserRole.MEMBER)

    resp = await anon_client.post(
        "/auth/login", json={"username": username, "password": password}
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码不正确"


async def test_register_consumes_invite(anon_client, test_db):
    code = await make_invite(test_db)

    resp = await anon_client.post(
        "/auth/register",
        json={"username": "bob", "password": "pw123456", "invite_code": code},
    )

    assert resp.status_code == 201
    assert resp.json() == {"username": "bob", "role": "member"}
    assert resp.cookies.get(COOKIE_NAME)          # 注册即登录

    async with test_db() as session:
        invite = await session.scalar(select(InviteCode).where(InviteCode.code == code))
        user = await session.scalar(select(User).where(User.username == "bob"))
    assert invite.used_by == user.id
    assert invite.used_at is not None
    assert user.role == UserRole.MEMBER            # 注册的一律是 member


async def test_register_code_is_single_use(anon_client, test_db):
    """spec 场景: 两人先后用同一枚码，第二人被拒。"""
    code = await make_invite(test_db)
    await anon_client.post(
        "/auth/register",
        json={"username": "bob", "password": "pw123456", "invite_code": code},
    )

    resp = await anon_client.post(
        "/auth/register",
        json={"username": "carol", "password": "pw123456", "invite_code": code},
    )

    assert resp.status_code == 400
    assert "已被使用" in resp.json()["detail"]
    async with test_db() as session:
        assert await session.scalar(select(User).where(User.username == "carol")) is None


async def test_register_concurrent_same_code_only_one_wins(anon_client, test_db):
    """并发双花：同一枚码被两个请求同时用，只能成一个。"""
    import asyncio

    code = await make_invite(test_db)
    results = await asyncio.gather(
        anon_client.post(
            "/auth/register",
            json={"username": "user1", "password": "pw123456", "invite_code": code},
        ),
        anon_client.post(
            "/auth/register",
            json={"username": "user2", "password": "pw123456", "invite_code": code},
        ),
        return_exceptions=True,
    )
    codes = [r.status_code for r in results if not isinstance(r, Exception)]

    assert codes.count(201) == 1, f"应只有一个注册成功，实际 {codes}"
    async with test_db() as session:
        users = list(await session.scalars(select(User)))
    assert len(users) == 1


async def test_register_unknown_code_rejected(anon_client, test_db):
    resp = await anon_client.post(
        "/auth/register",
        json={"username": "bob", "password": "pw123456", "invite_code": "ZZZZ9999"},
    )
    assert resp.status_code == 400
    assert "无效" in resp.json()["detail"]


async def test_register_duplicate_username_rejected(anon_client, test_db):
    await seed_user(test_db, "bob", UserRole.MEMBER)
    code = await make_invite(test_db)

    resp = await anon_client.post(
        "/auth/register",
        json={"username": "bob", "password": "pw123456", "invite_code": code},
    )

    assert resp.status_code == 409
    async with test_db() as session:
        invite = await session.scalar(select(InviteCode).where(InviteCode.code == code))
    assert invite.used_by is None                  # 失败的注册不该吃掉邀请码


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": "pw123456", "invite_code": "ABCD2345"},   # 用户名太短
        {"username": "bob", "password": "123", "invite_code": "ABCD2345"},       # 密码太短
        {"username": "bob", "password": "pw123456"},                             # 缺邀请码
    ],
)
async def test_register_validation(anon_client, test_db, payload):
    await make_invite(test_db)
    resp = await anon_client.post("/auth/register", json=payload)
    assert resp.status_code == 422


async def test_me_and_logout(anon_client, test_db):
    await seed_user(test_db, "alice", UserRole.MEMBER)
    await anon_client.post(
        "/auth/login", json={"username": "alice", "password": "pw123456"}
    )

    assert (await anon_client.get("/auth/me")).json()["username"] == "alice"

    await anon_client.post("/auth/logout")
    assert (await anon_client.get("/auth/me")).status_code == 401


async def test_me_requires_login(anon_client):
    resp = await anon_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "请先登录"


async def test_deleted_user_token_stops_working(anon_client, test_db):
    """token 里的身份每次查库核对——账号删了旧 token 立刻失效。"""
    user_id, cookies = await seed_user(test_db, "ghost", UserRole.MEMBER)
    anon_client.cookies.update(cookies)
    assert (await anon_client.get("/auth/me")).status_code == 200

    async with test_db() as session:
        await session.delete(await session.get(User, user_id))
        await session.commit()

    assert (await anon_client.get("/auth/me")).status_code == 401


async def test_role_change_takes_effect_immediately(anon_client, test_db):
    """token 里的 role 不可信：降级为 member 后旧 token 不能再当 admin 用。"""
    user_id, cookies = await seed_user(test_db, "demoted", UserRole.ADMIN)
    anon_client.cookies.update(cookies)
    assert (await anon_client.get("/auth/invites")).status_code == 200

    async with test_db() as session:
        user = await session.get(User, user_id)
        user.role = UserRole.MEMBER
        await session.commit()

    assert (await anon_client.get("/auth/invites")).status_code == 403


# ---------------- B5 邀请码管理 ----------------


async def test_admin_creates_and_lists_invites(api_client, test_db):
    created = await api_client.post("/auth/invites")

    assert created.status_code == 201
    code = created.json()["code"]
    assert len(code) == 8 and created.json()["used"] is False

    listed = await api_client.get("/auth/invites")
    assert listed.status_code == 200
    assert [row["code"] for row in listed.json()] == [code]


async def test_invite_list_shows_usage(api_client, anon_client, test_db):
    code = (await api_client.post("/auth/invites")).json()["code"]
    await anon_client.post(
        "/auth/register",
        json={"username": "bob", "password": "pw123456", "invite_code": code},
    )

    row = (await api_client.get("/auth/invites")).json()[0]

    assert row["used"] is True
    assert row["used_by_name"] == "bob"
    assert row["used_at"]


@pytest.mark.parametrize("method,path", [("post", "/auth/invites"), ("get", "/auth/invites")])
async def test_member_cannot_manage_invites(member_client, method, path):
    """spec 场景: member 调邀请码接口 → 403。"""
    resp = await getattr(member_client, method)(path)
    assert resp.status_code == 403
    assert "管理员" in resp.json()["detail"]


@pytest.mark.parametrize("method,path", [("post", "/auth/invites"), ("get", "/auth/invites")])
async def test_anonymous_cannot_manage_invites(anon_client, method, path):
    resp = await getattr(anon_client, method)(path)
    assert resp.status_code == 401


# ---------------- B6 守卫 ----------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/projects"),
        ("post", "/projects"),
        ("get", f"/projects/{uuid.uuid4()}"),
        ("get", f"/projects/{uuid.uuid4()}/report"),
        ("get", f"/projects/{uuid.uuid4()}/modules"),
        ("get", f"/projects/{uuid.uuid4()}/jobs"),
        ("post", f"/projects/{uuid.uuid4()}/index"),
        ("get", f"/projects/{uuid.uuid4()}/sessions"),
        ("get", f"/sessions/{uuid.uuid4()}/messages"),
        ("get", "/mcp-info"),
    ],
)
async def test_business_routes_require_login(anon_client, method, path):
    """spec 场景: 无 cookie 调业务 API → 401。"""
    resp = await getattr(anon_client, method)(path)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "请先登录"


@pytest.mark.parametrize("path", ["/health", "/auth/login", "/auth/register"])
async def test_exempt_routes_reachable_without_login(anon_client, path):
    """豁免清单：不能被守卫误伤。"""
    resp = await (
        anon_client.get(path) if path == "/health" else anon_client.post(path, json={})
    )
    assert resp.status_code != 401


async def test_mcp_endpoint_exempt_from_account_guard(anon_client):
    """spec 场景: MCP 走独立 Bearer token，不需要账号登录态。

    /mcp 是 ASGI mount 进来的子应用，账号守卫是路由级依赖，本就伸不进去——
    这条断言防的是将来有人手滑改成全局中间件。
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    try:
        resp = await anon_client.post("/mcp", json=body, headers=headers)
    except RuntimeError as e:
        # 本 fixture 不进 lifespan，MCP session manager 没启动。
        # 能抛到这里恰恰说明请求已经进了 MCP 子应用，而不是被账号守卫挡在门外
        assert "Task group" in str(e)
    else:
        assert resp.status_code != 401


async def test_member_cannot_delete_project(member_client, test_db):
    """spec 场景: member 删项目 → 403，数据无变化。"""
    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        pid = project.id

    resp = await member_client.delete(f"/projects/{pid}")

    assert resp.status_code == 403
    async with test_db() as session:
        assert await session.get(Project, pid) is not None


async def test_member_can_use_normal_features(member_client, test_db):
    """member 除管理外功能齐全——守卫不能把普通用户也挡在外面。"""
    created = await member_client.post(
        "/projects", json={"name": "p", "git_url": "https://example.com/x.git"}
    )
    assert created.status_code == 201
    assert (await member_client.get("/projects")).status_code == 200


async def test_forged_cookie_rejected(anon_client, test_db):
    import jwt

    await seed_user(test_db, "alice", UserRole.ADMIN)
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "exp": 9999999999},
        "attacker-key", algorithm="HS256",
    )
    anon_client.cookies.set(COOKIE_NAME, forged)

    assert (await anon_client.get("/projects")).status_code == 401


# ---------------- B7 会话归属 ----------------


async def seed_project(test_db) -> uuid.UUID:
    async with test_db() as session:
        project = Project(
            name="p", git_url="https://example.com/x.git", status=ProjectStatus.READY
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def test_created_session_belongs_to_creator(member_client, test_db):
    pid = await seed_project(test_db)

    resp = await member_client.post(f"/projects/{pid}/sessions", json={"title": "t"})

    assert resp.status_code == 201
    async with test_db() as session:
        chat = await session.get(ChatSession, uuid.UUID(resp.json()["id"]))
    assert chat.user_id == member_client.user_id


async def test_session_list_is_per_user(api_client, member_client, test_db):
    """spec 场景: B 的列表里不出现 A 的会话。"""
    pid = await seed_project(test_db)
    await api_client.post(f"/projects/{pid}/sessions", json={"title": "admin 的"})
    await member_client.post(f"/projects/{pid}/sessions", json={"title": "member 的"})

    admin_titles = [s["title"] for s in (await api_client.get(f"/projects/{pid}/sessions")).json()]
    member_titles = [s["title"] for s in (await member_client.get(f"/projects/{pid}/sessions")).json()]

    assert admin_titles == ["admin 的"]
    assert member_titles == ["member 的"]


async def test_others_session_messages_404(api_client, member_client, test_db):
    """spec 场景: 访问他人会话 → 404（不是 403——403 等于承认它存在）。"""
    pid = await seed_project(test_db)
    other = (await api_client.post(f"/projects/{pid}/sessions", json={"title": "t"})).json()

    resp = await member_client.get(f"/sessions/{other['id']}/messages")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "会话不存在"


async def test_others_session_ask_404(api_client, member_client, test_db):
    """他人会话不能被拿来提问（否则消息会写进别人的会话）。"""
    pid = await seed_project(test_db)
    other = (await api_client.post(f"/projects/{pid}/sessions", json={"title": "t"})).json()

    resp = await member_client.post(
        f"/sessions/{other['id']}/ask", json={"question": "偷看"}
    )

    assert resp.status_code == 404


async def test_legacy_null_session_visible_to_admin_only(api_client, member_client, test_db):
    """M8 之前的会话 user_id 为 NULL：只有 admin 看得到（spec）。"""
    pid = await seed_project(test_db)
    async with test_db() as session:
        legacy = ChatSession(project_id=pid, title="历史会话", user_id=None)
        session.add(legacy)
        await session.commit()
        await session.refresh(legacy)
        legacy_id = legacy.id

    admin_titles = [s["title"] for s in (await api_client.get(f"/projects/{pid}/sessions")).json()]
    member_titles = [s["title"] for s in (await member_client.get(f"/projects/{pid}/sessions")).json()]

    assert "历史会话" in admin_titles
    assert member_titles == []
    assert (await api_client.get(f"/sessions/{legacy_id}/messages")).status_code == 200
    assert (await member_client.get(f"/sessions/{legacy_id}/messages")).status_code == 404


async def test_own_session_messages_readable(member_client, test_db):
    pid = await seed_project(test_db)
    own = (await member_client.post(f"/projects/{pid}/sessions", json={"title": "t"})).json()

    resp = await member_client.get(f"/sessions/{own['id']}/messages")

    assert resp.status_code == 200
    assert resp.json() == []
