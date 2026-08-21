"""守卫依赖（M8 B6）：require_user / require_admin。

用 FastAPI 依赖而不是全局中间件——/mcp 是 ASGI mount 进来的子应用，
中间件会连它一起拦，而 MCP 有自己独立的 Bearer token 机制（M7 刚修过
root_path 绕过问题），账号守卫不该伸进去。
"""
import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.tables import User, UserRole
from app.services.auth.platform import (
    decode_platform_token,
    is_approved,
    resolve_platform_user,
)

logger = logging.getLogger(__name__)

UNAUTHENTICATED = "请先登录"
FORBIDDEN = "需要管理员权限"


async def _platform_user(
    request: Request, session: AsyncSession
) -> User | None:
    """平台 GitHub 登录态（M12 D2）。未启用或验签失败返回 None，交给密码登录兜底。"""
    if not settings.platform_auth_enabled:
        return None
    claims = decode_platform_token(
        request.cookies.get(settings.platform_cookie_name, "")
    )
    if claims is None:
        return None
    if not is_approved(claims):
        # 审核未通过/被拒：与未登录同样对待，不告诉对方"你的状态是 pending"
        logger.info("平台用户未通过审核（status=%s），拒绝访问", claims.get("status"))
        return None
    return await resolve_platform_user(claims, session)


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    """解析登录态。平台 GitHub 态优先，密码登录作为迁移期退路（M12 B1）。

    两条路径最后都落到同一个 User 记录，禁用判断也共用下面那一段。
    """
    user = await _platform_user(request, session)
    if user is not None:
        if user.disabled_at is not None:
            logger.info("已禁用账号尝试访问（平台登录态）：%s", user.username)
            return None
        return user

    # M12 阶段三：密码登录已删除，平台 GitHub 登录态是唯一来源。
    # 旧的 SECRET_KEY 签名路径一并移除——留着一条无人能签发的验证分支，等于给
    # 拿到 SECRET_KEY 的人留了一扇伪造登录态的门。
    return None


async def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, UNAUTHENTICATED)
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, FORBIDDEN)
    return user
