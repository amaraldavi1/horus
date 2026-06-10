# Horus VMS — backend-api

FastAPI service: public REST API (`/api/v1`), internal engine API (`/internal`),
WebSocket push (`/ws/events`, `/ws/status`) and the MQTT ingest loop.
Service contracts live in [`../docs/CONTRACTS.md`](../docs/CONTRACTS.md).

## Layout

```
app/
  main.py        # app factory + lifespan (admin seed, go2rtc sync, MQTT task)
  config.py      # pydantic-settings, env-driven (see below)
  db.py          # async engine/session (postgres+asyncpg or sqlite+aiosqlite)
  models.py      # SQLAlchemy 2.0 models (source of truth for migrations)
  schemas.py     # pydantic request/response shapes
  security.py    # JWT, bcrypt, Fernet credential encryption, RBAC deps
  utils.py       # URL masking, media path safety, timestamps
  routers/       # auth, users, cameras, zones, schedules, recordings,
                 # events, notifications, system, audit, ws, internal, health
  services/      # mqtt_listener, go2rtc, cache (redis), broadcast, notify,
                 # onvif, audit
alembic/         # async migrations (env.py reads DATABASE_URL)
tests/           # pytest suite (in-memory sqlite, httpx ASGI transport)
Dockerfile       # python:3.11-slim; runs migrations then uvicorn
```

## Environment variables

See `CONTRACTS.md` §7 and `app/config.py` for the full list. The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./horus.db` | `postgresql+asyncpg://...` in compose |
| `REDIS_URL` | `redis://localhost:6379/0` | status cache + login rate limit (best-effort) |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | engine event ingest (reconnects forever) |
| `SECRET_KEY` | dev value | JWT signing — set in production |
| `CREDENTIALS_KEY` | random per boot | Fernet key for camera credentials — pin it or URLs become undecryptable |
| `INTERNAL_API_TOKEN` | dev value | guards `/internal/*` (`X-Internal-Token`) |
| `GO2RTC_URL` | `http://localhost:1984` | stream registration (best-effort) |
| `MEDIA_ROOT` | `/media` | recordings/snapshots/clips root |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | unset | seed initial admin on startup if set |

Redis, MQTT and go2rtc are all best-effort: the API stays up (and tests run)
without them.

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite+aiosqlite:///./horus.db \
       SECRET_KEY=dev CREDENTIALS_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') \
       ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=changeme
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs: <http://localhost:8000/docs>. In production use
`docker compose up backend-api` from the repo root (the Dockerfile already
runs `alembic upgrade head` before uvicorn).

## Run tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use an in-memory SQLite database and httpx's ASGI transport; no
Postgres, Redis, MQTT or go2rtc needed (the suite points them at dead local
ports so the best-effort integrations fail fast).

## Migration workflow

1. Edit `app/models.py`.
2. Autogenerate against an up-to-date database:
   ```bash
   DATABASE_URL=sqlite+aiosqlite:///./horus.db alembic upgrade head
   DATABASE_URL=sqlite+aiosqlite:///./horus.db alembic revision --autogenerate -m "describe change"
   ```
3. Review the generated file in `alembic/versions/` (autogenerate misses
   server defaults and some constraint changes), then `alembic upgrade head`.

`alembic/env.py` is async and reads `DATABASE_URL` from the environment, so
the same migrations run on Postgres (compose) and SQLite (dev/tests).
