"""go2rtc stream management (CONTRACTS.md §3): cam{id} / cam{id}_sub naming."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Camera
from app.security import decrypt_secret
from app.utils import with_credentials

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


def _api(path: str) -> str:
    return f"{get_settings().go2rtc_url.rstrip('/')}{path}"


async def put_stream(name: str, src: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.put(_api("/api/streams"), params={"name": name, "src": src})
        resp.raise_for_status()


async def delete_stream(name: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(_api("/api/streams"), params={"src": name})
        if resp.status_code not in (200, 404):
            resp.raise_for_status()


def _decrypted_urls(camera: Camera) -> tuple[str | None, str | None]:
    username = decrypt_secret(camera.username_encrypted)
    password = decrypt_secret(camera.password_encrypted)
    main = with_credentials(decrypt_secret(camera.main_url_encrypted), username, password)
    sub = with_credentials(decrypt_secret(camera.sub_url_encrypted), username, password)
    return main, sub


async def sync_camera(camera: Camera) -> None:
    """Register/refresh go2rtc streams for a camera; best-effort."""
    main, sub = _decrypted_urls(camera)
    try:
        if camera.enabled and main:
            await put_stream(f"cam{camera.id}", main)
            if sub:
                await put_stream(f"cam{camera.id}_sub", sub)
            else:
                await delete_stream(f"cam{camera.id}_sub")
        else:
            await remove_camera(camera.id)
    except httpx.HTTPError as exc:
        logger.warning("go2rtc sync failed for camera %s: %s", camera.id, exc)


async def remove_camera(camera_id: int) -> None:
    try:
        await delete_stream(f"cam{camera_id}")
        await delete_stream(f"cam{camera_id}_sub")
    except httpx.HTTPError as exc:
        logger.warning("go2rtc stream removal failed for camera %s: %s", camera_id, exc)


async def sync_all(db: AsyncSession) -> None:
    """Startup sync of every enabled camera into go2rtc."""
    cameras = (await db.execute(select(Camera).where(Camera.enabled.is_(True)))).scalars().all()
    for camera in cameras:
        await sync_camera(camera)


def _walk(node: Any, found: dict[str, Any]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("codec_name", "codec") and isinstance(value, str) and "codec" not in found:
                found["codec"] = value.lower()
            elif key == "width" and isinstance(value, int) and "width" not in found:
                found["width"] = value
            elif key == "height" and isinstance(value, int) and "height" not in found:
                found["height"] = value
            else:
                _walk(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found)


async def probe_source(src: str) -> dict[str, Any]:
    """Probe a source URL through go2rtc; returns {ok, codec, width, height, error}."""
    name = f"probe_{uuid.uuid4().hex[:12]}"
    try:
        await put_stream(name, src)
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.get(_api("/api/streams"), params={"src": name})
            resp.raise_for_status()
            info = resp.json()
        found: dict[str, Any] = {}
        _walk(info, found)
        return {
            "ok": True,
            "codec": found.get("codec"),
            "width": found.get("width"),
            "height": found.get("height"),
            "error": None,
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "codec": None, "width": None, "height": None, "error": str(exc)}
    finally:
        try:
            await delete_stream(name)
        except httpx.HTTPError:
            pass


def public_stream_urls(camera: Camera) -> dict[str, str | None]:
    """Public URLs behind the nginx /go2rtc/ proxy (CONTRACTS.md §3)."""
    base = get_settings().go2rtc_public_path.rstrip("/")
    has_sub = camera.sub_url_encrypted is not None
    return {
        "webrtc_url": f"{base}/api/ws?src=cam{camera.id}",
        "hls_url": f"{base}/api/stream.m3u8?src=cam{camera.id}",
        "sub_webrtc_url": f"{base}/api/ws?src=cam{camera.id}_sub" if has_sub else None,
        "sub_hls_url": f"{base}/api/stream.m3u8?src=cam{camera.id}_sub" if has_sub else None,
    }
