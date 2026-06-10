"""System info: engine hardware report (Redis cache) and storage usage."""
from __future__ import annotations

import json
import logging
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Camera, Recording
from app.security import CurrentUser, get_permitted_camera_ids
from app.services.cache import get_redis
from app.services.mqtt_listener import HARDWARE_CACHE_KEY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/hardware")
async def hardware(_user: CurrentUser) -> dict:
    try:
        cached = await get_redis().get(HARDWARE_CACHE_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable for hardware report: %s", exc)
        cached = None
    if cached is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No hardware report received from the engine yet")
    return json.loads(cached)


@router.get("/storage")
async def storage(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    settings = get_settings()
    try:
        usage = shutil.disk_usage(settings.media_root)
        disk = {
            "path": settings.media_root,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    except OSError as exc:
        disk = {"path": settings.media_root, "error": str(exc)}

    permitted = await get_permitted_camera_ids(user, db)
    camera_query = select(Camera)
    if permitted is not None:
        camera_query = camera_query.where(Camera.id.in_(permitted))
    cameras = (await db.execute(camera_query.order_by(Camera.id))).scalars().all()

    sizes_query = select(
        Recording.camera_id,
        func.coalesce(func.sum(Recording.size_bytes), 0),
        func.count(Recording.id),
    ).group_by(Recording.camera_id)
    sizes = {row[0]: (row[1], row[2]) for row in (await db.execute(sizes_query)).all()}

    return {
        "disk": disk,
        "cameras": [
            {
                "camera_id": c.id,
                "name": c.name,
                "retention_days_continuous": c.retention_days_continuous,
                "retention_days_event": c.retention_days_event,
                "recordings_bytes": sizes.get(c.id, (0, 0))[0],
                "recordings_count": sizes.get(c.id, (0, 0))[1],
            }
            for c in cameras
        ],
    }
