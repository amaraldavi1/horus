"""Internal API for the video-engine (CONTRACTS.md §2), guarded by X-Internal-Token."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models import Camera, Recording, RecordingKind
from app.security import decrypt_secret
from app.utils import parse_ts, with_credentials

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().internal_api_token
    if x_internal_token is None or not secrets.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


class InternalRecordingIn(BaseModel):
    """HTTP fallback for the horus/recordings/{id} MQTT message (CONTRACTS.md §1.5)."""

    camera_id: int
    path: str
    started_at: str
    ended_at: str | None = None
    codec: str | None = None
    size_bytes: int = Field(default=0, ge=0)
    kind: RecordingKind = RecordingKind.continuous


def _camera_to_internal(camera: Camera) -> dict:
    username = decrypt_secret(camera.username_encrypted)
    password = decrypt_secret(camera.password_encrypted)
    return {
        "id": camera.id,
        "name": camera.name,
        "protocol": camera.protocol.value,
        "main_url": with_credentials(decrypt_secret(camera.main_url_encrypted), username, password),
        "sub_url": with_credentials(decrypt_secret(camera.sub_url_encrypted), username, password),
        "codec": camera.codec,
        "ptz": camera.ptz,
        "enabled": camera.enabled,
        "recording_mode": camera.recording_mode.value,
        "pre_buffer_s": camera.pre_buffer_s,
        "segment_s": camera.segment_s,
        "retention_days_continuous": camera.retention_days_continuous,
        "retention_days_event": camera.retention_days_event,
        "detect_objects": camera.detect_objects,
        "detect_fps": camera.detect_fps,
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "kind": z.kind.value,
                "polygon": z.polygon,
                "sensitivity": z.sensitivity,
                "min_area": z.min_area,
                "dwell_ms": z.dwell_ms,
            }
            for z in camera.zones
        ],
        "schedule": (
            {"timezone": camera.schedule.timezone, "rules": camera.schedule.rules}
            if camera.schedule is not None
            else None
        ),
    }


@router.get("/cameras", dependencies=[Depends(verify_internal_token)])
async def internal_cameras(db: Annotated[AsyncSession, Depends(get_db)]) -> list[dict]:
    cameras = (
        (
            await db.execute(
                select(Camera)
                .where(Camera.enabled.is_(True))
                .options(selectinload(Camera.zones), selectinload(Camera.schedule))
                .order_by(Camera.id)
            )
        )
        .scalars()
        .all()
    )
    return [_camera_to_internal(c) for c in cameras]


@router.post(
    "/recordings",
    dependencies=[Depends(verify_internal_token)],
    status_code=status.HTTP_201_CREATED,
)
async def internal_recordings(
    body: InternalRecordingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    if await db.get(Camera, body.camera_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")
    recording = Recording(
        camera_id=body.camera_id,
        path=body.path,
        started_at=parse_ts(body.started_at),
        ended_at=parse_ts(body.ended_at),
        codec=body.codec,
        size_bytes=body.size_bytes,
        kind=body.kind,
    )
    db.add(recording)
    await db.commit()
    return {"id": recording.id}
