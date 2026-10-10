"""安全：JWT 生成/校验 + 密码哈希。"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(subject),
        "type": token_type,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, "access",
                         timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, "refresh",
                         timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str) -> Optional[str]:
    """返回 sub(user_id)，无效或类型不符返回 None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload.get("sub")
    except JWTError:
        return None
