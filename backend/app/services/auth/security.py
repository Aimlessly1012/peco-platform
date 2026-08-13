"""认证基件（M8 B2）：密码哈希、JWT 签发/解析、邀请码生成。

不用 passlib：它 2020 年后停止维护，与 bcrypt 4/5 接连不兼容
（bcrypt 5 下连 verify 都会抛 ValueError，bcrypt 4 下每次加载吐一段 traceback）。
bcrypt 官方库的 hashpw/checkpw 就是 passlib 底下调的东西，直调更稳也更少一层。
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
TOKEN_TTL_DAYS = 7
COOKIE_NAME = "rag_token"

# 邀请码字符集：去掉 0/O/1/l/I——手抄邀请码时这几个最容易读错
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_LENGTH = 8

# bcrypt 只取前 72 字节，更长的部分被静默忽略（bcrypt 5 直接抛错）。
# 在这里显式截断，保证"哈希什么"与"校验什么"一致
BCRYPT_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    raw = (password or "").encode("utf-8")
    if len(raw) <= BCRYPT_MAX_BYTES:
        return raw
    # 按字节截断可能切断多字节字符，errors="ignore" 丢掉半个字符（确定性一致）
    return raw[:BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore").encode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验失败一律 False——坏哈希（历史脏数据）不该把请求炸成 500。"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        logger.warning("密码哈希格式非法，校验按失败处理")
        return False


def create_token(user_id: str, role: str, ttl_days: int = TOKEN_TTL_DAYS) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """解析并校验签名与过期。任何问题返回 None（调用方一律当未登录）。"""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.info("登录态已过期")
        return None
    except jwt.InvalidTokenError:
        logger.warning("登录态签名非法")
        return None
    if not payload.get("sub"):
        return None
    return payload


def generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))
