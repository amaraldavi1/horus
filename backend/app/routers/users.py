"""User management (admin only), including per-camera permission assignment."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, CameraPermission, User
from app.routers.auth import user_to_schema
from app.schemas import Page, UserCreate, UserOut, UserUpdate
from app.security import AdminUser, hash_password
from app.services.audit import client_ip, record_audit

router = APIRouter(prefix="/users", tags=["users"])


async def _set_camera_permissions(db: AsyncSession, user_id: int, camera_ids: list[int]) -> None:
    if camera_ids:
        existing = set(
            (await db.execute(select(Camera.id).where(Camera.id.in_(camera_ids)))).scalars().all()
        )
        missing = set(camera_ids) - existing
        if missing:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown camera ids: {sorted(missing)}")
    await db.execute(delete(CameraPermission).where(CameraPermission.user_id == user_id))
    for camera_id in set(camera_ids):
        db.add(CameraPermission(user_id=user_id, camera_id=camera_id))


@router.get("", response_model=Page[UserOut])
async def list_users(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> Page[UserOut]:
    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    users = (
        (await db.execute(select(User).order_by(User.id).offset((page - 1) * size).limit(size)))
        .scalars()
        .all()
    )
    items = [await user_to_schema(u, db) for u in users]
    return Page(items=items, total=total, page=page, size=size)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserOut:
    exists = (await db.execute(select(User.id).where(User.email == body.email))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=body.is_active,
    )
    db.add(user)
    await db.flush()
    await _set_camera_permissions(db, user.id, body.camera_ids)
    record_audit(db, user_id=admin.id, action="user.create", target=body.email, ip=client_ip(request))
    await db.commit()
    return await user_to_schema(user, db)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _admin: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return await user_to_schema(user, db)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"] != user.email:
        dup = (await db.execute(select(User.id).where(User.email == data["email"]))).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    camera_ids = data.pop("camera_ids", None)
    for field, value in data.items():
        setattr(user, field, value)
    if camera_ids is not None:
        await _set_camera_permissions(db, user.id, camera_ids)
    record_audit(db, user_id=admin.id, action="user.update", target=user.email, ip=client_ip(request))
    await db.commit()
    return await user_to_schema(user, db)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    record_audit(db, user_id=admin.id, action="user.delete", target=user.email, ip=client_ip(request))
    await db.delete(user)
    await db.commit()
