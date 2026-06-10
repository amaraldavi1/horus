"""Authentication: login (rate limited), refresh, logout, current profile."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import CameraPermission, User
from app.schemas import LoginRequest, RefreshRequest, TokenResponse, UserOut
from app.security import (
    CurrentUser,
    check_login_rate_limit,
    clear_login_failures,
    create_access_token,
    create_refresh_token,
    decode_token,
    register_login_failure,
    verify_password,
)
from app.services.audit import client_ip, record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


async def user_to_schema(user: User, db: AsyncSession) -> UserOut:
    rows = await db.execute(select(CameraPermission.camera_id).where(CameraPermission.user_id == user.id))
    return UserOut.model_validate(user, update={"camera_ids": sorted(rows.scalars().all())})


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=get_settings().refresh_token_days * 86400,
        path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    ip = client_ip(request) or "unknown"
    await check_login_rate_limit(ip, body.email)

    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        await register_login_failure(ip, body.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    await clear_login_failures(ip, body.email)
    record_audit(db, user_id=user.id, action="auth.login", target=user.email, ip=ip)
    await db.commit()

    refresh = create_refresh_token(user)
    _set_refresh_cookie(response, refresh)
    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=refresh,
        user=await user_to_schema(user, db),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: RefreshRequest | None = None,
) -> TokenResponse:
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
    payload = decode_token(token, "refresh")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_refresh = create_refresh_token(user)
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=new_refresh,
        user=await user_to_schema(user, db),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    record_audit(db, user_id=user.id, action="auth.logout", target=user.email, ip=client_ip(request))
    await db.commit()
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]) -> UserOut:
    return await user_to_schema(user, db)
