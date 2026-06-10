"""Detection events: filtered listing, detail, snapshot and clip serving."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Event, EventType
from app.schemas import EventOut, Page
from app.security import CurrentUser, ensure_camera_access, get_permitted_camera_ids
from app.utils import as_utc, resolve_media_path

router = APIRouter(prefix="/events", tags=["events"])


async def _get_accessible_event(event_id: str, user, db: AsyncSession) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    await ensure_camera_access(user, event.camera_id, db)
    return event


@router.get("", response_model=Page[EventOut])
async def list_events(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    camera_id: int | None = None,
    type: EventType | None = None,
    label: str | None = None,
    zone_id: int | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> Page[EventOut]:
    permitted = await get_permitted_camera_ids(user, db)
    filters = []
    if camera_id is not None:
        await ensure_camera_access(user, camera_id, db)
        filters.append(Event.camera_id == camera_id)
    elif permitted is not None:
        filters.append(Event.camera_id.in_(permitted))
    if type is not None:
        filters.append(Event.type == type)
    if label is not None:
        filters.append(Event.label == label)
    if zone_id is not None:
        filters.append(Event.zone_id == zone_id)
    if from_ is not None:
        filters.append(Event.started_at >= as_utc(from_))
    if to is not None:
        filters.append(Event.started_at <= as_utc(to))

    total = (await db.execute(select(func.count(Event.id)).where(*filters))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Event)
                .where(*filters)
                .order_by(Event.started_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return Page(items=[EventOut.model_validate(e) for e in rows], total=total, page=page, size=size)


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EventOut:
    return EventOut.model_validate(await _get_accessible_event(event_id, user, db))


@router.get("/{event_id}/snapshot")
async def event_snapshot(
    event_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    event = await _get_accessible_event(event_id, user, db)
    return FileResponse(resolve_media_path(event.snapshot_path), media_type="image/webp")


@router.get("/{event_id}/clip")
async def event_clip(
    event_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    event = await _get_accessible_event(event_id, user, db)
    return FileResponse(resolve_media_path(event.clip_path), media_type="video/mp4")
