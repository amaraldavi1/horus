"""Recording segments: timeline listing, range playback and export."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Recording, RecordingKind
from app.schemas import Page, RecordingOut
from app.security import CurrentUser, OperatorUser, ensure_camera_access, get_permitted_camera_ids
from app.services.audit import client_ip, record_audit
from app.utils import as_utc, resolve_media_path

router = APIRouter(prefix="/recordings", tags=["recordings"])


async def _get_accessible_recording(recording_id: int, user, db: AsyncSession) -> Recording:
    recording = await db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recording not found")
    await ensure_camera_access(user, recording.camera_id, db)
    return recording


@router.get("", response_model=Page[RecordingOut])
async def list_recordings(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    camera_id: int | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    kind: RecordingKind | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=500, ge=1, le=2000),
) -> Page[RecordingOut]:
    permitted = await get_permitted_camera_ids(user, db)
    filters = []
    if camera_id is not None:
        await ensure_camera_access(user, camera_id, db)
        filters.append(Recording.camera_id == camera_id)
    elif permitted is not None:
        filters.append(Recording.camera_id.in_(permitted))
    if from_ is not None:
        filters.append(Recording.started_at >= as_utc(from_))
    if to is not None:
        filters.append(Recording.started_at <= as_utc(to))
    if kind is not None:
        filters.append(Recording.kind == kind)

    total = (await db.execute(select(func.count(Recording.id)).where(*filters))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Recording)
                .where(*filters)
                .order_by(Recording.started_at)
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return Page(items=[RecordingOut.model_validate(r) for r in rows], total=total, page=page, size=size)


@router.get("/{recording_id}/play")
async def play_recording(
    recording_id: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    recording = await _get_accessible_recording(recording_id, user, db)
    path = resolve_media_path(recording.path)
    # Starlette's FileResponse honours HTTP Range requests for seeking.
    return FileResponse(path, media_type="video/mp4")


@router.get("/{recording_id}/export")
async def export_recording(
    recording_id: int,
    request: Request,
    user: OperatorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    recording = await _get_accessible_recording(recording_id, user, db)
    path = resolve_media_path(recording.path)
    record_audit(db, user_id=user.id, action="recording.export", target=f"recording:{recording_id}", ip=client_ip(request))
    await db.commit()
    started = recording.started_at.strftime("%Y%m%d-%H%M%S")
    filename = f"cam{recording.camera_id}_{started}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)
