"""Camera CRUD, ONVIF discovery, connection test, PTZ and stream URLs."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Camera, CameraProtocol
from app.schemas import (
    CameraCreate,
    CameraOut,
    CameraTestRequest,
    CameraTestResult,
    CameraUpdate,
    DiscoveredCamera,
    Page,
    PTZRequest,
    StreamUrls,
)
from app.security import (
    AdminUser,
    CurrentUser,
    OperatorUser,
    decrypt_secret,
    encrypt_secret,
    ensure_camera_access,
    get_permitted_camera_ids,
)
from app.services import go2rtc, onvif
from app.services.audit import client_ip, record_audit
from app.services.mqtt_listener import publish_command
from app.utils import mask_url

router = APIRouter(prefix="/cameras", tags=["cameras"])

_CREDENTIAL_FIELDS = {
    "main_url": "main_url_encrypted",
    "sub_url": "sub_url_encrypted",
    "username": "username_encrypted",
    "password": "password_encrypted",
}


def camera_to_schema(camera: Camera) -> CameraOut:
    """Public shape: URLs masked, username/password never exposed."""
    out = CameraOut.model_validate(camera)
    out.main_url = mask_url(decrypt_secret(camera.main_url_encrypted))
    out.sub_url = mask_url(decrypt_secret(camera.sub_url_encrypted))
    return out


@router.get("", response_model=Page[CameraOut])
async def list_cameras(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> Page[CameraOut]:
    permitted = await get_permitted_camera_ids(user, db)
    query = select(Camera)
    count_query = select(func.count(Camera.id))
    if permitted is not None:
        query = query.where(Camera.id.in_(permitted))
        count_query = count_query.where(Camera.id.in_(permitted))
    total = (await db.execute(count_query)).scalar_one()
    cameras = (
        (await db.execute(query.order_by(Camera.id).offset((page - 1) * size).limit(size))).scalars().all()
    )
    return Page(items=[camera_to_schema(c) for c in cameras], total=total, page=page, size=size)


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(
    body: CameraCreate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CameraOut:
    data = body.model_dump()
    encrypted = {column: encrypt_secret(data.pop(field)) for field, column in _CREDENTIAL_FIELDS.items()}
    camera = Camera(**data, **encrypted)
    db.add(camera)
    await db.flush()
    record_audit(db, user_id=admin.id, action="camera.create", target=f"camera:{camera.id}", ip=client_ip(request))
    await db.commit()
    await go2rtc.sync_camera(camera)
    await publish_command("reload_cameras", camera.id)
    return camera_to_schema(camera)


@router.post("/discover", response_model=list[DiscoveredCamera])
async def discover_cameras(_operator: OperatorUser) -> list[DiscoveredCamera]:
    found = await onvif.discover()
    return [DiscoveredCamera(**item) for item in found]


@router.post("/test", response_model=CameraTestResult)
async def test_camera(body: CameraTestRequest, _operator: OperatorUser) -> CameraTestResult:
    if body.protocol == CameraProtocol.usb:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="USB devices cannot be probed remotely")
    return CameraTestResult(**await go2rtc.probe_source(body.url))


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(
    camera_id: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CameraOut:
    camera = await ensure_camera_access(user, camera_id, db)
    return camera_to_schema(camera)


@router.put("/{camera_id}", response_model=CameraOut)
async def update_camera(
    camera_id: int,
    body: CameraUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CameraOut:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")
    data = body.model_dump(exclude_unset=True)
    for field, column in _CREDENTIAL_FIELDS.items():
        if field in data:
            setattr(camera, column, encrypt_secret(data.pop(field)))
    for field, value in data.items():
        setattr(camera, field, value)
    record_audit(db, user_id=admin.id, action="camera.update", target=f"camera:{camera.id}", ip=client_ip(request))
    await db.commit()
    await go2rtc.sync_camera(camera)
    await publish_command("reload_cameras", camera.id)
    return camera_to_schema(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Camera not found")
    record_audit(db, user_id=admin.id, action="camera.delete", target=f"camera:{camera_id}", ip=client_ip(request))
    await db.delete(camera)
    await db.commit()
    await go2rtc.remove_camera(camera_id)
    await publish_command("reload_cameras", camera_id)


@router.post("/{camera_id}/ptz")
async def ptz(
    camera_id: int,
    body: PTZRequest,
    user: OperatorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    camera = await ensure_camera_access(user, camera_id, db)
    if not camera.ptz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Camera does not support PTZ")
    main_url = decrypt_secret(camera.main_url_encrypted)
    if not main_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Camera has no usable URL for PTZ")
    await onvif.ptz_command(
        main_url,
        decrypt_secret(camera.username_encrypted),
        decrypt_secret(camera.password_encrypted),
        action=body.action,
        pan=body.pan,
        tilt=body.tilt,
        zoom=body.zoom,
        preset=body.preset,
    )
    return {"detail": "ok"}


@router.get("/{camera_id}/stream", response_model=StreamUrls)
async def stream_urls(
    camera_id: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamUrls:
    camera = await ensure_camera_access(user, camera_id, db)
    return StreamUrls(**go2rtc.public_stream_urls(camera))
