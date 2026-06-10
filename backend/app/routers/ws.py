"""Realtime websockets: /ws/events and /ws/status.

Clients authenticate with `?token=<access JWT>`. Messages come from the
in-process broadcast hub (fed by the MQTT listener) and are filtered by the
user's per-camera permissions.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette import status as ws_status

from app.db import SessionLocal
from app.security import get_permitted_camera_ids, user_from_token
from app.services.broadcast import hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


async def _authorize(websocket: WebSocket) -> set[int] | None:
    """Return permitted camera ids (None = all); raises on auth failure."""
    token = websocket.query_params.get("token")
    if not token:
        raise PermissionError("token query parameter required")
    async with SessionLocal() as db:
        user = await user_from_token(token, db)
        return await get_permitted_camera_ids(user, db)


async def _serve(websocket: WebSocket, topic: str) -> None:
    try:
        permitted = await _authorize(websocket)
    except Exception:  # noqa: BLE001 - any auth failure closes with policy violation
        await websocket.close(code=ws_status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    queue = hub.subscribe(topic)
    receiver = asyncio.create_task(websocket.receive_text())
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                receiver.result()  # raises WebSocketDisconnect when the client left
                receiver = asyncio.create_task(websocket.receive_text())
                continue
            message = getter.result()
            camera_id = message.get("data", {}).get("camera_id")
            if permitted is None or camera_id in permitted:
                await websocket.send_json(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        receiver.cancel()
        hub.unsubscribe(topic, queue)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await _serve(websocket, "events")


@router.websocket("/ws/status")
async def ws_status_endpoint(websocket: WebSocket) -> None:
    await _serve(websocket, "status")
