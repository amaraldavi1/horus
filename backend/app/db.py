"""Async database engine/session, compatible with postgresql+asyncpg and sqlite+aiosqlite."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def _create_engine() -> AsyncEngine:
    url = get_settings().database_url
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs.pop("pool_pre_ping")
        if ":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite://"):
            # Single shared connection so in-memory DBs survive across sessions (tests).
            kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = _create_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session
