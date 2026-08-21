"""管理员初始化与密钥强度检查（M8 B3），在 lifespan 里调用。"""
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.tables import User, UserRole

logger = logging.getLogger(__name__)

DEFAULT_SECRET = "dev-secret-key"
MIN_SECRET_BYTES = 32


def check_secret_key() -> bool:
    """JWT 用 SECRET_KEY 签名：默认值或过短 = 谁都能伪造 admin 登录态。

    只 warning 不拦启动——本机开发要能一把跑起来；生产由 DEPLOY.md 要求改。
    """
    secret = settings.secret_key or ""
    if secret == DEFAULT_SECRET:
        logger.warning(
            "SECRET_KEY 仍是默认值，登录态可被伪造。生产务必改："
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
        return False
    if len(secret.encode()) < MIN_SECRET_BYTES:
        logger.warning(
            "SECRET_KEY 只有 %d 字节，低于 HMAC-SHA256 推荐的 %d 字节",
            len(secret.encode()), MIN_SECRET_BYTES,
        )
        return False
    return True


