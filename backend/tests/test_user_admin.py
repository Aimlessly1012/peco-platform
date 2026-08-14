"""用户管理单测（M11 B2-B5）。

两个重点：
1. JWT 无状态 → 禁用必须靠守卫查库才能即刻生效（不等 7 天过期）
2. 两条防自锁护栏——少一条就能一次误操作把自己关在系统外
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.tables import (
    ChatMessage,
    ChatSession,
    InviteCode,
    Project,
    ProjectStatus,
    User,
    UserRole,
)
from app.api.auth import (
    CANNOT_DISABLE_LAST_ADMIN,
    CANNOT_DISABLE_SELF,
    disable_blocker,
)
from app.services.auth.security import COOKIE_NAME, create_token, hash_password
from tests.conftest import seed_user


async def make_user(test_db, username, role=UserRole.MEMBER, **fields) -> User:
    async with test_db() as session:
        user = User(
            username=username, password_hash=hash_password("pw123456"),
            role=role, **fields,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def get_user(test_db, user_id) -> User:
    async with test_db() as session:
        return await session.get(User, user_id)


# ---------------- B2 登录 ----------------


async def test_login_records_last_login(anon_client, test_db):
    user = await make_user(test_db, "alice")
    assert user.last_login_at is None

    await anon_client.post(
        "/auth/login", json={"username": "alice", "password": "pw123456"}
    )

    refreshed = await get_user(test_db, user.id)
    assert refreshed.last_login_at is not None


async def test_disabled_user_cannot_login(anon_client, test_db):
    """spec 场景: 被禁用账号输入正确密码 → 401，文案与密码错误一致。"""
    await make_user(test_db, "banned", disabled_at=datetime.now(timezone.utc))

    resp = await anon_client.post(
        "/auth/login", json={"username": "banned", "password": "pw123456"}
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码不正确"   # 不泄露"被禁用"这个事实
    assert resp.cookies.get(COOKIE_NAME) is None


async def test_disabled_login_message_matches_wrong_password(anon_client, test_db):
    """两条路径的文案必须逐字相同，否则可以据此枚举出哪些账号被禁。"""
    await make_user(test_db, "banned", disabled_at=datetime.now(timezone.utc))
    await make_user(test_db, "normal")

    disabled = await anon_client.post(
        "/auth/login", json={"username": "banned", "password": "pw123456"}
    )
    wrong_pw = await anon_client.post(
        "/auth/login", json={"username": "normal", "password": "wrong-password"}
    )

    assert disabled.status_code == wrong_pw.status_code == 401
    assert disabled.json() == wrong_pw.json()


async def test_enabled_user_can_login_again(anon_client, test_db):
    user = await make_user(test_db, "restored", disabled_at=datetime.now(timezone.utc))
    async with test_db() as session:
        target = await session.get(User, user.id)
        target.disabled_at = None
        await session.commit()

    resp = await anon_client.post(
        "/auth/login", json={"username": "restored", "password": "pw123456"}
    )
    assert resp.status_code == 200


# ---------------- B3 守卫即刻生效 ----------------


async def test_valid_token_dies_immediately_on_disable(anon_client, test_db):
    """spec 场景: 持有效 JWT 的用户被禁 → 下一个请求立即 401，不等 token 过期。

    这是 M11 最容易做错的一点：JWT 无状态，不查库的话旧 token 能用满 7 天。
    """
    user = await make_user(test_db, "victim")
    anon_client.cookies.set(COOKIE_NAME, create_token(str(user.id), user.role))
    assert (await anon_client.get("/auth/me")).status_code == 200

    async with test_db() as session:
        target = await session.get(User, user.id)
        target.disabled_at = datetime.now(timezone.utc)
        await session.commit()

    # 同一个 token，没有任何重新登录
    assert (await anon_client.get("/auth/me")).status_code == 401
    assert (await anon_client.get("/projects")).status_code == 401


async def test_re_enable_restores_access_with_same_token(anon_client, test_db):
    """恢复后同一个未过期 token 应该又能用——禁用不是签名失效。"""
    user = await make_user(test_db, "victim", disabled_at=datetime.now(timezone.utc))
    anon_client.cookies.set(COOKIE_NAME, create_token(str(user.id), user.role))
    assert (await anon_client.get("/auth/me")).status_code == 401

    async with test_db() as session:
        target = await session.get(User, user.id)
        target.disabled_at = None
        await session.commit()

    assert (await anon_client.get("/auth/me")).status_code == 200


async def test_disabled_admin_loses_admin_routes(anon_client, test_db):
    """被禁的 admin 连管理接口也进不去（守卫在角色判断之前）。"""
    user = await make_user(test_db, "exadmin", UserRole.ADMIN,
                           disabled_at=datetime.now(timezone.utc))
    anon_client.cookies.set(COOKIE_NAME, create_token(str(user.id), UserRole.ADMIN))

    assert (await anon_client.get("/auth/users")).status_code == 401


# ---------------- B4 用户列表 ----------------


async def test_user_list_requires_admin(member_client):
    """spec 场景: member 调用 → 403。"""
    resp = await member_client.get("/auth/users")
    assert resp.status_code == 403


async def test_user_list_requires_login(anon_client):
    assert (await anon_client.get("/auth/users")).status_code == 401


async def test_user_list_shows_profile(api_client, test_db):
    """spec 场景: 角色、注册与最后登录、来源邀请码、会话与提问数量。"""
    member = await make_user(test_db, "bob")
    async with test_db() as session:
        session.add(InviteCode(code="ABCD2345", used_by=member.id,
                               used_at=datetime.now(timezone.utc)))
        project = Project(name="p", git_url="https://x.git", status=ProjectStatus.READY)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        chat = ChatSession(project_id=project.id, user_id=member.id, title="t")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        session.add_all([
            ChatMessage(session_id=chat.id, role="user", content="问题一"),
            ChatMessage(session_id=chat.id, role="assistant", content="回答"),
            ChatMessage(session_id=chat.id, role="user", content="问题二"),
        ])
        await session.commit()

    rows = (await api_client.get("/auth/users")).json()
    bob = next(r for r in rows if r["username"] == "bob")

    assert bob["role"] == "member"
    assert bob["disabled"] is False
    assert bob["invite_code"] == "ABCD2345"
    assert bob["session_count"] == 1
    assert bob["message_count"] == 2      # 只算用户提问，不含 assistant 回复
    assert bob["created_at"]


async def test_admin_without_invite_shows_null(api_client, test_db):
    """管理员初始账号没有邀请码，要能正常显示空而不是报错。"""
    rows = (await api_client.get("/auth/users")).json()
    admin = next(r for r in rows if r["username"] == "admin")

    assert admin["invite_code"] is None
    assert admin["role"] == "admin"
    assert admin["session_count"] == 0
    assert admin["message_count"] == 0


async def test_user_list_ordered_by_created_desc(api_client, test_db):
    import asyncio

    await make_user(test_db, "first")
    await asyncio.sleep(0.01)
    await make_user(test_db, "second")

    names = [r["username"] for r in (await api_client.get("/auth/users")).json()]
    assert names.index("second") < names.index("first")


async def test_user_list_marks_disabled(api_client, test_db):
    await make_user(test_db, "banned", disabled_at=datetime.now(timezone.utc))

    rows = (await api_client.get("/auth/users")).json()
    banned = next(r for r in rows if r["username"] == "banned")
    assert banned["disabled"] is True


async def test_disabled_at_timestamp_is_exposed(api_client, test_db):
    """PM 验收回归：前端按 disabled_at 判断状态并显示「禁用于 X」。

    只回 disabled 布尔时前端读到 undefined——状态永远显示「正常」、按钮永远是
    「禁用」、已禁用计数恒为 0，禁用功能在界面上等于不存在（后端却一切正常，
    所以只测后端自身契约的用例全绿也发现不了）。
    """
    stamp = datetime.now(timezone.utc)
    await make_user(test_db, "banned", disabled_at=stamp)
    await make_user(test_db, "normal")

    rows = (await api_client.get("/auth/users")).json()
    banned = next(r for r in rows if r["username"] == "banned")
    normal = next(r for r in rows if r["username"] == "normal")

    assert banned["disabled_at"] is not None
    assert banned["disabled_at"].startswith(stamp.strftime("%Y-%m-%d"))
    assert normal["disabled_at"] is None


async def test_disable_enable_responses_carry_timestamp(api_client, test_db):
    """禁用/恢复的返回体也要带时间戳——前端拿它就地更新那一行，不必重拉列表。"""
    user = await make_user(test_db, "target")

    disabled = (await api_client.post(f"/auth/users/{user.id}/disable")).json()
    assert disabled["disabled"] is True
    assert disabled["disabled_at"] is not None

    enabled = (await api_client.post(f"/auth/users/{user.id}/enable")).json()
    assert enabled["disabled"] is False
    assert enabled["disabled_at"] is None


async def test_user_list_never_exposes_password_hash(api_client, test_db):
    """列表是给人看的画像，密码哈希绝不能出现在响应里。"""
    import json

    await make_user(test_db, "bob")
    body = json.dumps((await api_client.get("/auth/users")).json())

    assert "password" not in body
    assert "$2b$" not in body


# ---------------- B5 禁用 / 恢复 ----------------


async def test_disable_then_enable(api_client, test_db):
    member = await make_user(test_db, "bob")

    disabled = await api_client.post(f"/auth/users/{member.id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["disabled"] is True
    assert (await get_user(test_db, member.id)).disabled_at is not None

    enabled = await api_client.post(f"/auth/users/{member.id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["disabled"] is False
    assert (await get_user(test_db, member.id)).disabled_at is None


async def test_disable_is_idempotent(api_client, test_db):
    member = await make_user(test_db, "bob")
    first = await api_client.post(f"/auth/users/{member.id}/disable")
    disabled_at = (await get_user(test_db, member.id)).disabled_at

    second = await api_client.post(f"/auth/users/{member.id}/disable")

    assert first.status_code == second.status_code == 200
    # 重复禁用不刷新时间戳——那会让"何时被禁"这个信息丢失
    assert (await get_user(test_db, member.id)).disabled_at == disabled_at


async def test_enable_idempotent_on_active_user(api_client, test_db):
    member = await make_user(test_db, "bob")
    resp = await api_client.post(f"/auth/users/{member.id}/enable")
    assert resp.status_code == 200
    assert resp.json()["disabled"] is False


async def test_cannot_disable_self(api_client, test_db):
    """spec 场景: 禁用自己 → 400，状态不变。"""
    async with test_db() as session:
        me = await session.scalar(select(User).where(User.username == "admin"))

    resp = await api_client.post(f"/auth/users/{me.id}/disable")

    assert resp.status_code == 400
    assert "自己" in resp.json()["detail"]
    assert (await get_user(test_db, me.id)).disabled_at is None


async def test_cannot_disable_last_active_admin(api_client, test_db):
    """spec 场景: 禁用最后一个启用的 admin → 400。

    构造：另有一个 admin（非当前登录者），且它是唯一…… 这里当前登录者本身也是 admin，
    所以先把 fixture 的 admin 之外再造一个，禁掉它之后剩一个就该被拦。
    """
    second = await make_user(test_db, "admin2", UserRole.ADMIN)

    # 此时有两个启用 admin，禁用第二个应当成功
    assert (await api_client.post(f"/auth/users/{second.id}/disable")).status_code == 200

    # 现在只剩当前登录的 admin，再禁它会同时撞上"自己"与"最后一个 admin"
    async with test_db() as session:
        me = await session.scalar(select(User).where(User.username == "admin"))
    resp = await api_client.post(f"/auth/users/{me.id}/disable")
    assert resp.status_code == 400
    assert resp.json()["detail"] == CANNOT_DISABLE_SELF   # 自己这条先拦


def make_stub_user(role=UserRole.MEMBER, disabled=False, user_id=None):
    return User(
        id=user_id or uuid.uuid4(), username="x", password_hash="h", role=role,
        disabled_at=datetime.now(timezone.utc) if disabled else None,
    )


def test_blocker_stops_self_disable():
    me = make_stub_user(UserRole.ADMIN)
    assert disable_blocker(me, me, active_admin_count=5) == CANNOT_DISABLE_SELF


def test_blocker_stops_last_active_admin():
    """第二条护栏的直接验证。

    当前 API 形态下操作者必然是启用的 admin，所以"目标是最后一个启用 admin"必然
    等价于"目标是自己"、被第一条先拦——这条护栏因此在真实调用里触发不到。
    留着它是为将来加角色降级功能兜底，所以在这里单独验证它自身是对的。
    """
    target = make_stub_user(UserRole.ADMIN)
    operator = make_stub_user(UserRole.ADMIN)
    assert disable_blocker(target, operator, 1) == CANNOT_DISABLE_LAST_ADMIN


def test_blocker_allows_when_other_admins_active():
    target = make_stub_user(UserRole.ADMIN)
    operator = make_stub_user(UserRole.ADMIN)
    assert disable_blocker(target, operator, 2) is None


def test_blocker_allows_member_regardless_of_admin_count():
    target = make_stub_user(UserRole.MEMBER)
    operator = make_stub_user(UserRole.ADMIN)
    assert disable_blocker(target, operator, 1) is None


def test_blocker_allows_already_disabled_admin():
    """已禁用的 admin 再点一次禁用不该被"最后一个 admin"拦住。"""
    target = make_stub_user(UserRole.ADMIN, disabled=True)
    operator = make_stub_user(UserRole.ADMIN)
    assert disable_blocker(target, operator, 1) is None


async def test_disabled_admin_not_counted_as_active(api_client, test_db):
    """已禁用的 admin 不算"启用的 admin"——否则护栏会被绕过。"""
    ghost = await make_user(test_db, "ghost_admin", UserRole.ADMIN,
                            disabled_at=datetime.now(timezone.utc))
    async with test_db() as session:
        me = await session.scalar(select(User).where(User.username == "admin"))

    # ghost 已禁用，启用 admin 只剩当前登录者 → 禁自己必须被拦（400）
    resp = await api_client.post(f"/auth/users/{me.id}/disable")
    assert resp.status_code == 400
    assert (await get_user(test_db, ghost.id)).disabled_at is not None


async def test_disable_unknown_user_404(api_client):
    resp = await api_client.post(f"/auth/users/{uuid.uuid4()}/disable")
    assert resp.status_code == 404


@pytest.mark.parametrize("action", ["disable", "enable"])
async def test_member_cannot_manage_users(member_client, test_db, action):
    other = await make_user(test_db, "bob")
    resp = await member_client.post(f"/auth/users/{other.id}/{action}")
    assert resp.status_code == 403


async def test_disable_keeps_sessions_and_messages(api_client, test_db):
    """spec 场景: 禁用后再恢复，历史会话与消息完好。"""
    member = await make_user(test_db, "bob")
    async with test_db() as session:
        project = Project(name="p", git_url="https://x.git", status=ProjectStatus.READY)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        chat = ChatSession(project_id=project.id, user_id=member.id, title="保留我")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        session.add(ChatMessage(session_id=chat.id, role="user", content="问题"))
        await session.commit()
        chat_id, project_id = chat.id, project.id

    await api_client.post(f"/auth/users/{member.id}/disable")
    await api_client.post(f"/auth/users/{member.id}/enable")

    async with test_db() as session:
        assert await session.get(ChatSession, chat_id) is not None
        assert await session.get(Project, project_id) is not None       # 项目也不动
        messages = list(await session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == chat_id)
        ))
    assert len(messages) == 1


async def test_disable_does_not_touch_projects(api_client, test_db):
    """M11 决策：项目全局共享，与创建者无关，禁用不影响任何项目。"""
    member = await make_user(test_db, "bob")
    async with test_db() as session:
        session.add(Project(name="共享项目", git_url="https://x.git"))
        await session.commit()

    await api_client.post(f"/auth/users/{member.id}/disable")

    projects = (await api_client.get("/projects")).json()
    assert [p["name"] for p in projects] == ["共享项目"]
