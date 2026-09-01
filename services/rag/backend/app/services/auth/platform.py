"""接受 peco-platform 的 GitHub 登录态（M12 D2）。

平台的 NextAuth 把默认的 JWE 换成了 JWS(HS256)，所以后端能用共享密钥直接验签
cookie 里的 session token，不需要平台加一层 API 代理——那条代理要转发 SSE 与 MCP
长连接，而这条链路已经踩过 M6（nginx 缓冲吞流）与 M7（root_path 让 MCP 鉴权失效）
两个坑，为一次鉴权重走一遍不划算。

AUTH_JWT_SECRET 为空 = 整条平台路径关闭，行为回到 M8 的密码登录。
"""
import logging

import jwt
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
STATUS_APPROVED = "approved"

# 平台 token 的字段名容错：NextAuth 的 jwt 回调怎么塞取决于平台侧实现，
# 这几种写法都见过，认宽一点比上线后对不上强
GITHUB_ID_KEYS = ("github_id", "githubId", "githubID")
ROLE_KEYS = ("role",)
STATUS_KEYS = ("status",)


def _first(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def decode_platform_token(token: str) -> dict | None:
    """验签并解出 {github_id, role, status, name}。任何问题返回 None。

    只验签名与过期——token 里的 status 是平台每次 jwt 回调查库刷新的，
    可以直接信；本地禁用态另在 RAG 侧独立判断（见 deps.current_user）。
    """
    if not settings.platform_auth_enabled or not token:
        return None
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.info("平台登录态已过期")
        return None
    except jwt.InvalidTokenError as e:
        # 平台若还没切成 JWS，这里会拿到 JWE 而解不开——日志要能看出是这个原因
        logger.warning("平台登录态验签失败（%s）", type(e).__name__)
        return None
    if not isinstance(payload, dict):
        return None

    github_id = _first(payload, GITHUB_ID_KEYS)
    if not github_id:
        logger.warning("平台登录态缺少 github_id 字段，无法映射用户")
        return None

    status = _first(payload, STATUS_KEYS)
    if not status:
        # 宁可全拒也不能默认放行：平台一定会带 status，缺了说明字段名对不上
        logger.warning("平台登录态缺少 status 字段，按未批准处理")
        return None

    return {
        "github_id": github_id,
        "role": _first(payload, ROLE_KEYS) or "member",
        "status": status,
        # 平台禁用用户时只写 disabled_at、不改 status，所以必须单独取这个标志，
        # 否则「在 /admin 点了禁用」对 RAG 完全无效（PM 验收实测放行了）
        "disabled": bool(payload.get("disabled")),
        "name": str(payload.get("name") or payload.get("login") or "").strip(),
    }


def is_approved(claims: dict) -> bool:
    """平台侧是否放行：approved 且未被禁用。

    与 RAG 本地的 disabled_at 是**并集**关系——任一侧禁用都拒绝。平台禁用是运营动作，
    RAG 本地禁用是 M11 留下的管理能力，两者都该有效，取并集才不会互相覆盖。
    """
    return claims.get("status") == STATUS_APPROVED and not claims.get("disabled")


async def resolve_platform_user(claims: dict, session) -> "User | None":
    """平台 claims → RAG 侧 User 记录（M12 B2）。

    选择在 RAG 侧建档而不是直接读 platform_users：chat_sessions.user_id 外键指向
    users.id，改指过去要迁移历史会话，而 M8 的密码账号根本没有 github_id、无从映射，
    会把历史会话变成孤儿。这里只做一层映射，阶段三合表时再带迁移脚本。

    角色以平台为准（每次登录同步），禁用态以 RAG 本地为准（M11 的管理接口仍然有效）。
    """
    from sqlalchemy import select

    from app.models.tables import User, UserRole

    github_id = claims["github_id"]
    user = await session.scalar(select(User).where(User.github_id == github_id))

    role = UserRole.ADMIN if claims.get("role") == UserRole.ADMIN else UserRole.MEMBER
    if user is not None:
        if user.role != role:
            # 平台是角色的权威来源，改了要跟上
            user.role = role
            await session.commit()
        return user

    user = User(
        username=_unique_username(claims, github_id),
        github_id=github_id,
        role=role,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # 同一用户的并发请求同时建档：唯一约束兜住，回头再查一次即可
        await session.rollback()
        return await session.scalar(select(User).where(User.github_id == github_id))
    await session.refresh(user)
    logger.info("首次见到平台用户，已在 RAG 侧建档：%s", user.username)
    return user


def _unique_username(claims: dict, github_id: str) -> str:
    """显示名。平台的 name 可能重名或为空，兜底用 gh-<id> 保证唯一。"""
    name = (claims.get("name") or "").strip()[:24]
    return name and f"{name}#{github_id[-4:]}" or f"gh-{github_id}"[:32]
