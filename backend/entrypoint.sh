#!/bin/sh
# Backend entrypoint: wait for the database, apply migrations, start the API.
set -e

python - <<'EOF'
import socket
import sys
import time

from sqlalchemy.engine import make_url

from app.config import get_settings

raw = get_settings().database_url
try:
    url = make_url(raw)
except Exception as exc:  # noqa: BLE001
    print(f"[entrypoint] FATAL: DATABASE_URL is not a valid SQLAlchemy URL: {exc}\n"
          "[entrypoint] Unset DATABASE_URL in your .env to use the bundled postgres\n"
          "[entrypoint] service (the URL is then assembled safely from POSTGRES_*).",
          file=sys.stderr, flush=True)
    sys.exit(1)

if url.host:  # network database; sqlite URLs have no host and skip the wait
    host = url.host
    port = url.port or 5432
    print(f"[entrypoint] waiting for database at {host}:{port} ...", flush=True)
    deadline = time.monotonic() + 120
    attempt = 0
    while True:
        attempt += 1
        try:
            socket.create_connection((host, port), timeout=3).close()
            print(f"[entrypoint] database reachable (attempt {attempt})", flush=True)
            break
        except OSError as exc:
            if time.monotonic() >= deadline:
                print(f"[entrypoint] FATAL: cannot reach database at {host}:{port}: {exc}\n"
                      f"[entrypoint] The host above came from DATABASE_URL. If it is not\n"
                      f"[entrypoint] 'postgres', a DATABASE_URL in your .env is overriding\n"
                      f"[entrypoint] the compose default — unset it to use the bundled\n"
                      f"[entrypoint] postgres service.", file=sys.stderr, flush=True)
                sys.exit(1)
            print(f"[entrypoint] database at {host}:{port} not ready ({exc}); "
                  "retrying in 2s", flush=True)
            time.sleep(2)

    # TCP is up; verify credentials with a real connection so auth problems
    # produce actionable guidance instead of a raw alembic traceback.
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def _check() -> None:
        engine = create_async_engine(raw, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    last_exc: Exception | None = None
    for _ in range(3):
        try:
            asyncio.run(_check())
            print("[entrypoint] database credentials OK", flush=True)
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(2)
    if last_exc is not None:
        message = str(last_exc)
        if "password authentication failed" in message.lower():
            print("[entrypoint] FATAL: the database rejected the password.\n"
                  "[entrypoint] The postgres data volume keeps the password from its\n"
                  "[entrypoint] FIRST initialization; changing POSTGRES_PASSWORD in .env\n"
                  "[entrypoint] later has no effect. Either restore the original password\n"
                  "[entrypoint] or reset the (empty) database volume:\n"
                  "[entrypoint]   docker compose down && docker volume rm horus_pgdata\n"
                  "[entrypoint]   docker compose up -d\n"
                  "[entrypoint] (recordings in the media volume are not touched)",
                  file=sys.stderr, flush=True)
        else:
            print(f"[entrypoint] FATAL: database connection failed: {message}",
                  file=sys.stderr, flush=True)
        sys.exit(1)
EOF

alembic upgrade head
# `exec` makes uvicorn PID 1 so it receives SIGTERM for a clean shutdown.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
