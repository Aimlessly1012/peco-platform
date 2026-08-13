"""认证 API（M8 B4/B5）：登录、邀请码注册、当前用户、登出、邀请码管理。"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.tables import InviteCode, User, UserRole
from app.schemas import InviteCodeOut, LoginRequest, RegisterRequest, UserOut
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
