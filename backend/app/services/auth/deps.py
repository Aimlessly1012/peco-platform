"""守卫依赖（M8 B6）：require_user / require_admin。

用 FastAPI 依赖而不是全局中间件——/mcp 是 ASGI mount 进来的子应用，
中间件会连它一起拦，而 MCP 有自己独立的 Bearer token 机制（M7 刚修过
root_path 绕过问题），账号守卫不该伸进去。
"""
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.tables import User, UserRole
from app.services.auth.security import COOKIE_NAME, decode_token

UNAUTHENTICATED = "请先登录"
FORBIDDEN = "需要管理员权限"


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    """解析 cookie 里的登录态。无/过期/伪造/用户已删 → None。"""
    payload = decode_token(request.cookies.get(COOKIE_NAME, ""))
    if payload is None:
        return None
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        return None
    # 每次查库：账号被删或改角色后，旧 token 立即失效（token 里的 role 不可信）
    return await session.get(User, user_id)


async def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, UNAUTHENTICATED)
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, FORBIDDEN)
    return user
