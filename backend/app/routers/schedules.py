"""Per-camera recording schedule (one row per camera, upserted)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, Schedule
from app.schemas import ScheduleOut, ScheduleUpdate
from app.security import AdminUser, CurrentUser, ensure_camera_access
from app.services.audit import client_ip, record_audit
from app.services.mqtt_listener import publish_command

router = APIRouter(prefix="/cameras/{camera_id}/schedule", tags=["schedules"])


@router.get("", response_model=ScheduleOut)
async def get_schedule(
    camera_id: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleOut:
    await ensure_camera_access(user, camera_id, db)
    schedule = (await db.execute(select(Schedule).where(Schedule.camera_id == camera_id))).scalar_one_or_none()
    if schedule is None:
        return ScheduleOut(camera_id=camera_id, timezone="UTC", rules=[])
    return ScheduleOut.model_validate(schedule)


@router.put("", response_model=ScheduleOut)
async def put_schedule(
    camera_id: int,
    body: ScheduleUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleOut:
    if await db.get(Camera, camera_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")
    schedule = (await db.execute(select(Schedule).where(Schedule.camera_id == camera_id))).scalar_one_or_none()
    rules = [rule.model_dump() for rule in body.rules]
    if schedule is None:
        schedule = Schedule(camera_id=camera_id, timezone=body.timezone, rules=rules)
        db.add(schedule)
    else:
        schedule.timezone = body.timezone
        schedule.rules = rules
    record_audit(db, user_id=admin.id, action="schedule.update", target=f"camera:{camera_id}", ip=client_ip(request))
    await db.commit()
    await publish_command("reload_cameras", camera_id)
    return ScheduleOut.model_validate(schedule)
