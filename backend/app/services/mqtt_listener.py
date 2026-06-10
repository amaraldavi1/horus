"""MQTT subscriber task: ingests engine messages per CONTRACTS.md §1.

- horus/events/{id}      -> upsert events row, broadcast, dispatch notifications
- horus/recordings/{id}  -> insert recordings row
- horus/status/{id}      -> cache in Redis + broadcast
- horus/engine/hardware  -> cache in Redis
"""
from __future__ import annotations

import asyncio
import json
import logging

import aiomqtt

from app.config import get_settings
from app.db import SessionLocal
from app.models import Camera, Event, EventType, Recording, RecordingKind
from app.services.broadcast import hub
from app.services.cache import get_redis
from app.services.notify import dispatch_event_notifications
from app.utils import parse_ts

logger = logging.getLogger(__name__)

HARDWARE_CACHE_KEY = "horus:hardware"
STATUS_CACHE_PREFIX = "horus:status:"
COMMAND_TOPIC = "horus/engine/command"


async def _handle_event(camera_id: int, payload: dict) -> None:
    phase = payload.get("phase", "start")
    event_id = payload.get("event_id")
    if not event_id:
        logger.warning("Event message without event_id for camera %s", camera_id)
        return

    async with SessionLocal() as db:
        if await db.get(Camera, camera_id) is None:
            logger.warning("Event for unknown camera %s ignored", camera_id)
            return
        event = await db.get(Event, event_id)
        is_new = event is None
        if event is None:
            event = Event(
                id=event_id,
                camera_id=camera_id,
                type=EventType(payload.get("type", "motion")),
                started_at=parse_ts(payload.get("started_at")),
            )
            db.add(event)
        for field in ("label", "snapshot_path", "clip_path"):
            if payload.get(field) is not None:
                setattr(event, field, payload[field])
        if payload.get("confidence") is not None:
            event.confidence = float(payload["confidence"])
        if payload.get("zone_id") is not None:
            event.zone_id = int(payload["zone_id"])
        if payload.get("duration_s") is not None:
            event.duration_s = float(payload["duration_s"])
        if payload.get("ended_at") is not None:
            event.ended_at = parse_ts(payload["ended_at"])
        await db.commit()

    hub.publish("events", {"type": "event", "data": payload})
    if is_new or phase == "start":
        await dispatch_event_notifications(payload)


async def _handle_recording(camera_id: int, payload: dict) -> None:
    async with SessionLocal() as db:
        if await db.get(Camera, camera_id) is None:
            logger.warning("Recording for unknown camera %s ignored", camera_id)
            return
        db.add(
            Recording(
                camera_id=camera_id,
                path=payload["path"],
                started_at=parse_ts(payload.get("started_at")),
                ended_at=parse_ts(payload.get("ended_at")),
                codec=payload.get("codec"),
                size_bytes=int(payload.get("size_bytes", 0)),
                kind=RecordingKind(payload.get("kind", "continuous")),
            )
        )
        await db.commit()


async def _handle_status(camera_id: int, payload: dict) -> None:
    try:
        await get_redis().set(f"{STATUS_CACHE_PREFIX}{camera_id}", json.dumps(payload), ex=3600)
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        logger.debug("Could not cache camera status in Redis: %s", exc)
    hub.publish("status", {"type": "status", "data": payload})


async def _handle_hardware(payload: dict) -> None:
    try:
        await get_redis().set(HARDWARE_CACHE_KEY, json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not cache hardware report in Redis: %s", exc)


async def _dispatch(topic: str, raw: bytes) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Non-JSON MQTT payload on %s", topic)
        return

    parts = topic.split("/")
    try:
        if len(parts) == 3 and parts[1] == "events":
            await _handle_event(int(parts[2]), payload)
        elif len(parts) == 3 and parts[1] == "recordings":
            await _handle_recording(int(parts[2]), payload)
        elif len(parts) == 3 and parts[1] == "status":
            await _handle_status(int(parts[2]), payload)
        elif topic == "horus/engine/hardware":
            await _handle_hardware(payload)
    except Exception as exc:  # noqa: BLE001 - a bad message must not kill the listener
        logger.exception("Failed handling MQTT message on %s: %s", topic, exc)


async def mqtt_listener() -> None:
    """Long-running task; reconnects forever with backoff."""
    settings = get_settings()
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                identifier="horus-backend",
            ) as client:
                logger.info("MQTT connected to %s:%s", settings.mqtt_host, settings.mqtt_port)
                await client.subscribe("horus/#")
                async for message in client.messages:
                    await _dispatch(str(message.topic), bytes(message.payload))
        except asyncio.CancelledError:
            raise
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT connection lost (%s); retrying in 5s", exc)
            await asyncio.sleep(5)


async def publish_command(action: str, camera_id: int | None = None, params: dict | None = None) -> None:
    """Publish a backend->engine command (CONTRACTS.md §1.4); best-effort."""
    settings = get_settings()
    payload = {"action": action, "camera_id": camera_id, "params": params or {}}
    try:
        async with aiomqtt.Client(hostname=settings.mqtt_host, port=settings.mqtt_port) as client:
            await client.publish(COMMAND_TOPIC, json.dumps(payload))
    except aiomqtt.MqttError as exc:
        logger.warning("Could not publish engine command %s: %s", action, exc)
