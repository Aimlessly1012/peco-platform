"""认证 API（M8 B4/B5）：登录、邀请码注册、当前用户、登出、邀请码管理。"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.tables import ChatMessage, ChatSession, InviteCode, User, UserRole
from app.schemas import (
    InviteCodeOut,
    LoginRequest,
    RegisterRequest,
    UserAdminOut,
    UserOut,
)
from app.services.auth.deps import require_admin, require_user
from app.services.auth.security import (
    COOKIE_NAME,
    TOKEN_TTL_DAYS,
    create_token,
    generate_invite_code,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# 登录失败一律同一句：区分"用户名不存在"与"密码错误"等于送人一个用户名枚举接口
LOGIN_FAILED = "用户名或密码不正确"


def _set_login_cookie(response: Response, user: User) -> None:
    """httpOnly 防 XSS 读取；SameSite=Lax 防 CSRF 又不挡正常跳转导航。

    没加 Secure：当前是 HTTP 部署，加了 cookie 直接不下发。上 HTTPS 后必须补
    （DEPLOY.md 已记）。
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_token(str(user.id), user.role),
        httponly=True,
        samesite="lax",
        path="/",
        max_age=TOKEN_TTL_DAYS * 24 * 3600,
    )


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    user = await session.scalar(
        select(User).where(User.username == payload.username)
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, LOGIN_FAILED)
    if user.disabled_at is not None:
        # 与密码错误同一文案：区分开来等于告诉试探者"这个账号存在，只是被禁了"
        logger.info("已禁用账号尝试登录：%s", user.username)
        raise HTTPException(401, LOGIN_FAILED)

    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    _set_login_cookie(response, user)
    return UserOut(username=user.username, role=user.role)


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    payload: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """邀请码注册。邀请码消耗与建号在同一事务里，并发下只有一个人能用掉同一枚码。"""
    code = payload.invite_code.strip().upper()

    if await session.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "用户名已被占用")

    # used_by 有外键：必须先把用户行 flush 进事务，再去抢邀请码——
    # 反过来写在 Postgres 上直接 FK 违反（SQLite 测试库不查 FK，单测抓不到）
    user = User(
        id=uuid.uuid4(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=UserRole.MEMBER,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        # 同名用户并发注册：唯一约束兜底
        await session.rollback()
        raise HTTPException(409, "用户名已被占用") from None

    # 条件更新即抢占：WHERE used_by IS NULL 让并发的第二个请求更新到 0 行
    claimed = await session.execute(
        InviteCode.__table__.update()
        .where(InviteCode.code == code, InviteCode.used_by.is_(None))
        .values(used_by=user.id, used_at=datetime.now(timezone.utc))
        .returning(InviteCode.id)
    )
    if claimed.first() is None:
        # 分不清"不存在"与"已用完"时按已用提示——邀请码不是秘密，不需要掩护
        exists = await session.scalar(
            select(func.count()).select_from(InviteCode).where(InviteCode.code == code)
        )
        await session.rollback()
        raise HTTPException(400, "邀请码已被使用" if exists else "邀请码无效")

    await session.commit()

    _set_login_cookie(response, user)
    logger.info("新用户注册：%s（邀请码 %s）", user.username, code)
    return UserOut(username=user.username, role=user.role)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return UserOut(username=user.username, role=user.role)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    # 登出不要求登录态：cookie 已过期时也该能清干净
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/invites", response_model=InviteCodeOut, status_code=201)
async def create_invite(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """生成一枚邀请码。极小概率撞码时重试几次（8 位 31 进制，实际撞不上）。"""
    for _ in range(5):
        invite = InviteCode(code=generate_invite_code(), created_by=admin.id)
        session.add(invite)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(invite)
        return InviteCodeOut(
            code=invite.code, used=False, created_at=invite.created_at
        )
    raise HTTPException(500, "邀请码生成失败，请重试")


@router.get("/invites", response_model=list[InviteCodeOut])
async def list_invites(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.execute(
        select(InviteCode, User.username)
        .outerjoin(User, InviteCode.used_by == User.id)
        .order_by(desc(InviteCode.created_at))
        .limit(200)
    )
    return [
        InviteCodeOut(
            code=invite.code,
            used=invite.used_by is not None,
            used_by_name=username,
            used_at=invite.used_at,
            created_at=invite.created_at,
        )
        for invite, username in rows
    ]


# ---------------- 用户管理（M11，仅 admin） ----------------

CANNOT_DISABLE_SELF = "不能禁用自己"
CANNOT_DISABLE_LAST_ADMIN = "不能禁用最后一个启用状态的管理员"


def disable_blocker(target: User, operator: User, active_admin_count: int) -> str | None:
    """能否禁用 target？返回拒绝原因，None 表示放行（M11 B5 两条防自锁护栏）。

    提成纯函数是为了让第二条能被独立验证：当前 API 形态下操作者必然是个启用的 admin，
    所以"目标是最后一个启用 admin"必然等价于"目标就是自己"，第一条会先拦下。
    第二条因此在实际调用中被遮蔽，但它是角色调整/降级功能加进来之后的最后防线，
    不能因为"现在触发不到"就删掉。
    """
    if target.id == operator.id:
        return CANNOT_DISABLE_SELF
    if (
        target.role == UserRole.ADMIN
        and target.disabled_at is None
        and active_admin_count <= 1
    ):
        return CANNOT_DISABLE_LAST_ADMIN
    return None


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """用户画像列表（M11 B4）：注册时间倒序，含来源邀请码与会话/提问计数。

    计数走子查询聚合，避免 N+1；邀请码由 invite_codes.used_by 反查
    （管理员初始账号没有邀请码，返回 null）。
    """
    session_counts = (
        select(ChatSession.user_id, func.count().label("n"))
        .where(ChatSession.user_id.is_not(None))
        .group_by(ChatSession.user_id)
        .subquery()
    )
    # 提问数只算 user 角色的消息——assistant 回复不是"用户提了多少问"
    message_counts = (
        select(ChatSession.user_id, func.count().label("n"))
        .join(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id.is_not(None), ChatMessage.role == "user")
        .group_by(ChatSession.user_id)
        .subquery()
    )

    rows = await session.execute(
        select(
            User,
            InviteCode.code,
            func.coalesce(session_counts.c.n, 0),
            func.coalesce(message_counts.c.n, 0),
        )
        .outerjoin(InviteCode, InviteCode.used_by == User.id)
        .outerjoin(session_counts, session_counts.c.user_id == User.id)
        .outerjoin(message_counts, message_counts.c.user_id == User.id)
        .order_by(desc(User.created_at))
    )
    return [
        UserAdminOut(
            id=user.id,
            username=user.username,
            role=user.role,
            disabled=user.disabled_at is not None,
            disabled_at=user.disabled_at,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            invite_code=code,
            session_count=session_count,
            message_count=message_count,
        )
        for user, code, session_count, message_count in rows
    ]


async def _target_user(user_id: uuid.UUID, session: AsyncSession) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    return user


@router.post("/users/{user_id}/disable", response_model=UserAdminOut)
async def disable_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """禁用登录权限（M11 B5）。数据一概不动，随时可恢复。

    两条护栏都是"防止把自己锁在系统外"：少任何一条，一次误操作就再也进不来。
    """
    user = await _target_user(user_id, session)
    active_admins = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.disabled_at.is_(None))
    )
    blocker = disable_blocker(user, admin, active_admins or 0)
    if blocker:
        raise HTTPException(400, blocker)

    if user.disabled_at is None:
        user.disabled_at = datetime.now(timezone.utc)
        await session.commit()
        logger.info("管理员 %s 禁用了账号 %s", admin.username, user.username)
    return _user_admin_out(user)


@router.post("/users/{user_id}/enable", response_model=UserAdminOut)
async def enable_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """恢复登录权限。历史会话与消息本就没删，恢复后直接可用。"""
    user = await _target_user(user_id, session)
    if user.disabled_at is not None:
        user.disabled_at = None
        await session.commit()
        logger.info("管理员 %s 恢复了账号 %s", admin.username, user.username)
    return _user_admin_out(user)


def _user_admin_out(user: User) -> UserAdminOut:
    """禁用/恢复的返回体：只回状态，计数留给列表接口（这里不值得再聚合一次）。"""
    return UserAdminOut(
        id=user.id,
        username=user.username,
        role=user.role,
        disabled=user.disabled_at is not None,
        disabled_at=user.disabled_at,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )
