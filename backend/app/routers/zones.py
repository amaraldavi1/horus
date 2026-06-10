"""Detection zone CRUD (nested under cameras)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, Zone
from app.schemas import ZoneCreate, ZoneOut
from app.security import AdminUser, CurrentUser, ensure_camera_access
from app.services.audit import client_ip, record_audit
from app.services.mqtt_listener import publish_command

router = APIRouter(prefix="/cameras/{camera_id}/zones", tags=["zones"])


async def _get_zone(db: AsyncSession, camera_id: int, zone_id: int) -> Zone:
    zone = await db.get(Zone, zone_id)
    if zone is None or zone.camera_id != camera_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Zone not found")
    return zone


async def _ensure_camera_exists(db: AsyncSession, camera_id: int) -> None:
    if await db.get(Camera, camera_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")


@router.get("", response_model=list[ZoneOut])
async def list_zones(
    camera_id: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ZoneOut]:
    await ensure_camera_access(user, camera_id, db)
    zones = (await db.execute(select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.id))).scalars().all()
    return [ZoneOut.model_validate(z) for z in zones]


@router.post("", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
async def create_zone(
    camera_id: int,
    body: ZoneCreate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOut:
    await _ensure_camera_exists(db, camera_id)
    zone = Zone(camera_id=camera_id, **body.model_dump())
    db.add(zone)
    await db.flush()
    record_audit(db, user_id=admin.id, action="zone.create", target=f"camera:{camera_id}/zone:{zone.id}", ip=client_ip(request))
    await db.commit()
    await publish_command("reload_zones", camera_id)
    return ZoneOut.model_validate(zone)


@router.put("/{zone_id}", response_model=ZoneOut)
async def update_zone(
    camera_id: int,
    zone_id: int,
    body: ZoneCreate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZoneOut:
    zone = await _get_zone(db, camera_id, zone_id)
    for field, value in body.model_dump().items():
        setattr(zone, field, value)
    record_audit(db, user_id=admin.id, action="zone.update", target=f"camera:{camera_id}/zone:{zone_id}", ip=client_ip(request))
    await db.commit()
    await publish_command("reload_zones", camera_id)
    return ZoneOut.model_validate(zone)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    camera_id: int,
    zone_id: int,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    zone = await _get_zone(db, camera_id, zone_id)
    record_audit(db, user_id=admin.id, action="zone.delete", target=f"camera:{camera_id}/zone:{zone_id}", ip=client_ip(request))
    await db.delete(zone)
    await db.commit()
    await publish_command("reload_zones", camera_id)
