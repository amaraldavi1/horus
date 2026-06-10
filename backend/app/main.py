"""FastAPI application factory and lifespan wiring."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import User, UserRole
from app.routers import (
    audit,
    auth,
    cameras,
    events,
    health,
    internal,
    notifications,
    recordings,
    schedules,
    system,
    users,
    ws,
    zones,
)
from app.security import hash_password
from app.services import go2rtc
from app.services.cache import close_redis
from app.services.mqtt_listener import mqtt_listener

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _create_initial_admin() -> None:
    settings = get_settings()
    if not (settings.admin_email and settings.admin_password):
        return
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(User.id).where(User.email == settings.admin_email))
        ).scalar_one_or_none()
        if existing is not None:
            return
        db.add(
            User(
                name="Administrator",
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                role=UserRole.admin,
                is_active=True,
            )
        )
        await db.commit()
        logger.info("Initial admin user created: %s", settings.admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await _create_initial_admin()
    except Exception as exc:  # noqa: BLE001 - don't block startup (e.g. DB not migrated yet)
        logger.error("Initial admin creation failed: %s", exc)

    try:
        async with SessionLocal() as db:
            await go2rtc.sync_all(db)
    except Exception as exc:  # noqa: BLE001 - go2rtc may not be reachable yet
        logger.warning("go2rtc startup sync failed: %s", exc)

    mqtt_task = asyncio.create_task(mqtt_listener(), name="mqtt-listener")
    try:
        yield
    finally:
        mqtt_task.cancel()
        try:
            await mqtt_task
        except asyncio.CancelledError:
            pass
        await close_redis()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Horus VMS API", version="1.0.0", lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = "/api/v1"
    app.include_router(health.router, prefix=api)
    app.include_router(auth.router, prefix=api)
    app.include_router(users.router, prefix=api)
    app.include_router(cameras.router, prefix=api)
    app.include_router(zones.router, prefix=api)
    app.include_router(schedules.router, prefix=api)
    app.include_router(recordings.router, prefix=api)
    app.include_router(events.router, prefix=api)
    app.include_router(notifications.router, prefix=api)
    app.include_router(system.router, prefix=api)
    app.include_router(audit.router, prefix=api)
    # Engine-facing API lives outside /api/v1 (CONTRACTS.md §2).
    app.include_router(internal.router)
    # Websockets are reachable both at /ws/* and /api/v1/ws/*.
    app.include_router(ws.router)
    app.include_router(ws.router, prefix=api)
    return app


app = create_app()
