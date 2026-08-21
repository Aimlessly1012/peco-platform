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





