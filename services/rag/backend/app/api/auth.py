"""认证 API。

M12 阶段三起身份来自平台的 GitHub 登录（见 services/auth/platform.py），
这里只剩当前用户、登出与 M11 的用户管理；密码登录与邀请码注册已删除。
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.tables import ChatMessage, ChatSession, User, UserRole
from app.schemas import (
    UserAdminOut,
    UserOut,
)
from app.services.auth.deps import require_admin, require_user
from app.services.auth.security import COOKIE_NAME

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])




@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return UserOut(username=user.username, role=user.role)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    # 登出不要求登录态：cookie 已过期时也该能清干净
    response.delete_cookie(COOKIE_NAME, path="/")


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
    """用户画像列表（M11 B4）：注册时间倒序，含会话/提问计数。

    计数走子查询聚合，避免 N+1。邀请码那一列随 M8 体系一起删了（M12 阶段三）。
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
            func.coalesce(session_counts.c.n, 0),
            func.coalesce(message_counts.c.n, 0),
        )
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
            session_count=session_count,
            message_count=message_count,
        )
        for user, session_count, message_count in rows
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
