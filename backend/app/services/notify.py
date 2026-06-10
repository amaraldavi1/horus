"""Best-effort notification dispatch (webhook / email / web push) for new events."""
from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Notification, NotificationChannel, PushSubscription

logger = logging.getLogger(__name__)

try:
    from pywebpush import webpush  # type: ignore[import-untyped]

    PUSH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    webpush = None  # type: ignore[assignment]
    PUSH_AVAILABLE = False


def _matches(filters: dict, event: dict) -> bool:
    """Match an event payload against a notification's filters JSON."""
    if not filters:
        return True
    camera_ids = filters.get("camera_ids")
    if camera_ids and event.get("camera_id") not in camera_ids:
        return False
    types = filters.get("types")
    if types and event.get("type") not in types:
        return False
    labels = filters.get("labels")
    if labels and event.get("label") not in labels:
        return False
    min_confidence = filters.get("min_confidence")
    confidence = event.get("confidence")
    if min_confidence is not None and (confidence is None or confidence < min_confidence):
        return False
    return True


async def _send_webhook(target: str, event: dict) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        await client.post(target, json={"type": "event", "data": event})


def _send_email_sync(target: str, event: dict) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        logger.debug("SMTP not configured, skipping email notification")
        return
    message = EmailMessage()
    label = event.get("label") or event.get("type", "event")
    message["Subject"] = f"[Horus] {label} on camera {event.get('camera_id')}"
    message["From"] = settings.smtp_from
    message["To"] = target
    message.set_content(json.dumps(event, indent=2, default=str))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def _send_push_sync(subscriptions: list[dict], event: dict) -> None:
    settings = get_settings()
    if not (PUSH_AVAILABLE and settings.vapid_private_key):
        logger.debug("Web push not configured (pywebpush/VAPID missing), skipping")
        return
    payload = json.dumps({"type": "event", "data": event}, default=str)
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Web push delivery failed: %s", exc)


async def dispatch_event_notifications(event: dict) -> None:
    """Fan a new event out to all matching, enabled notification channels."""
    async with SessionLocal() as db:
        notifications = (
            (await db.execute(select(Notification).where(Notification.enabled.is_(True)))).scalars().all()
        )
        matching = [n for n in notifications if _matches(n.filters or {}, event)]
        push_subs: list[dict] = []
        if any(n.channel == NotificationChannel.push for n in matching):
            push_subs = [
                s.subscription
                for s in (await db.execute(select(PushSubscription))).scalars().all()
            ]

    for notification in matching:
        try:
            if notification.channel == NotificationChannel.webhook:
                await _send_webhook(notification.target, event)
            elif notification.channel == NotificationChannel.email:
                await asyncio.to_thread(_send_email_sync, notification.target, event)
            elif notification.channel == NotificationChannel.push:
                await asyncio.to_thread(_send_push_sync, push_subs, event)
        except Exception as exc:  # noqa: BLE001 - notifications must never break ingestion
            logger.warning(
                "Notification %s (%s) failed: %s", notification.id, notification.channel.value, exc
            )
