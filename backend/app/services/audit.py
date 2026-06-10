"""Audit log helper."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record_audit(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    target: str | None = None,
    ip: str | None = None,
) -> None:
    """Stage an audit row; committed together with the caller's transaction."""
    db.add(AuditLog(user_id=user_id, action=action, target=target, ip=ip))
