"""Authentication, authorization, credential encryption and login rate limiting."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Camera, CameraPermission, User, UserRole
from app.services.cache import get_redis

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


# --- JWT ----------------------------------------------------------------------


def _create_token(user: User, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM)


def create_access_token(user: User) -> str:
    return _create_token(user, "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user: User) -> str:
    return _create_token(user, "refresh", timedelta(days=get_settings().refresh_token_days))


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"Expected a {expected_type} token")
    return payload


# --- Camera credential encryption (Fernet) -----------------------------------


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().credentials_key.encode())


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt camera credential (wrong CREDENTIALS_KEY?)")
        return None


# --- Current user / role dependencies ----------------------------------------


async def user_from_token(token: str, db: AsyncSession) -> User:
    payload = decode_token(token, "access")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await user_from_token(credentials.credentials, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_operator(user: CurrentUser) -> User:
    if user.role not in (UserRole.admin, UserRole.operator):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Operator role or higher required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
OperatorUser = Annotated[User, Depends(require_operator)]


# --- Per-camera permissions ---------------------------------------------------


async def get_permitted_camera_ids(user: User, db: AsyncSession) -> set[int] | None:
    """Return permitted camera ids for the user; None means unrestricted (admin)."""
    if user.role == UserRole.admin:
        return None
    rows = await db.execute(select(CameraPermission.camera_id).where(CameraPermission.user_id == user.id))
    return set(rows.scalars().all())


async def ensure_camera_access(user: User, camera_id: int, db: AsyncSession) -> Camera:
    """Raise 404 if camera does not exist, 403 if the user cannot access it."""
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")
    permitted = await get_permitted_camera_ids(user, db)
    if permitted is not None and camera_id not in permitted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No permission for this camera")
    return camera


# --- Login brute-force rate limit (Redis, best-effort) ------------------------


def _rate_limit_key(ip: str, email: str) -> str:
    return f"horus:login_fail:{ip}:{email.lower()}"


async def check_login_rate_limit(ip: str, email: str) -> None:
    settings = get_settings()
    try:
        fails = await get_redis().get(_rate_limit_key(ip, email))
    except Exception:  # noqa: BLE001 - rate limiting is best-effort when Redis is down
        logger.warning("Redis unavailable, skipping login rate limit check")
        return
    if fails is not None and int(fails) >= settings.login_max_failures:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts, try again later",
        )


async def register_login_failure(ip: str, email: str) -> None:
    settings = get_settings()
    try:
        redis = get_redis()
        key = _rate_limit_key(ip, email)
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, settings.login_window_seconds)
            await pipe.execute()
    except Exception:  # noqa: BLE001
        logger.warning("Redis unavailable, could not register login failure")


async def clear_login_failures(ip: str, email: str) -> None:
    try:
        await get_redis().delete(_rate_limit_key(ip, email))
    except Exception:  # noqa: BLE001
        pass
