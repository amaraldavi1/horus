"""Notification channel CRUD (admin) and web push subscription registration."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Notification, PushSubscription
from app.schemas import NotificationCreate, NotificationOut, NotificationUpdate, PushSubscribeRequest
from app.security import AdminUser, CurrentUser
from app.services.audit import client_ip, record_audit

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(_admin: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]) -> list[NotificationOut]:
    rows = (await db.execute(select(Notification).order_by(Notification.id))).scalars().all()
    return [NotificationOut.model_validate(n) for n in rows]


@router.post("", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
async def create_notification(
    body: NotificationCreate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationOut:
    notification = Notification(**body.model_dump())
    db.add(notification)
    await db.flush()
    record_audit(db, user_id=admin.id, action="notification.create", target=f"notification:{notification.id}", ip=client_ip(request))
    await db.commit()
    return NotificationOut.model_validate(notification)


@router.put("/{notification_id}", response_model=NotificationOut)
async def update_notification(
    notification_id: int,
    body: NotificationUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationOut:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(notification, field, value)
    record_audit(db, user_id=admin.id, action="notification.update", target=f"notification:{notification_id}", ip=client_ip(request))
    await db.commit()
    return NotificationOut.model_validate(notification)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    record_audit(db, user_id=admin.id, action="notification.delete", target=f"notification:{notification_id}", ip=client_ip(request))
    await db.delete(notification)
    await db.commit()


@router.post("/push/subscribe", status_code=status.HTTP_201_CREATED)
async def push_subscribe(
    body: PushSubscribeRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    db.add(PushSubscription(user_id=user.id, subscription=body.subscription))
    await db.commit()
    return {"detail": "Subscribed"}
