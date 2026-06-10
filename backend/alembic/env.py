"""Async Alembic environment.

Reads the database URL from the DATABASE_URL environment variable (same value
docker-compose injects), falling back to the application settings default.
Works with both postgresql+asyncpg and sqlite+aiosqlite URLs.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Settings reads DATABASE_URL from the environment and otherwise assembles
    # the URL from POSTGRES_* variables with the password percent-encoded.
    from app.config import get_settings

    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting ('alembic upgrade head --sql')."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    # render_as_batch makes future ALTERs work on SQLite; harmless on Postgres.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
