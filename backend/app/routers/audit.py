"""Audit trail listing (admin only)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AuditLog
from app.schemas import AuditOut, Page
from app.security import AdminUser

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditOut])
async def list_audit(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: int | None = None,
    action: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> Page[AuditOut]:
    filters = []
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if action is not None:
        filters.append(AuditLog.action == action)

    total = (await db.execute(select(func.count(AuditLog.id)).where(*filters))).scalar_one()
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(*filters)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return Page(items=[AuditOut.model_validate(a) for a in rows], total=total, page=page, size=size)
