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
EOF

alembic upgrade head
# `exec` makes uvicorn PID 1 so it receives SIGTERM for a clean shutdown.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
