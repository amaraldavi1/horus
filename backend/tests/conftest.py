"""Shared test fixtures.

Environment is forced BEFORE any app import: in-memory SQLite, and Redis /
MQTT / go2rtc pointed at unroutable local ports so the app's best-effort
integrations fail fast instead of needing real services.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["CREDENTIALS_KEY"] = Fernet.generate_key().decode()
os.environ["INTERNAL_API_TOKEN"] = "test-internal-token"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["MQTT_HOST"] = "127.0.0.1"
os.environ["MQTT_PORT"] = "1"
os.environ["GO2RTC_URL"] = "http://127.0.0.1:1"
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User, UserRole  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

# Note: email-validator rejects reserved domains like .local, hence example.com.
ADMIN_EMAIL = "admin@example.com"
OPERATOR_EMAIL = "operator@example.com"
VIEWER_EMAIL = "viewer@example.com"
PASSWORD = "correct-horse-battery"

_password_hash: str | None = None


def password_hash() -> str:
    """Hash the shared test password once (bcrypt is intentionally slow)."""
    global _password_hash
    if _password_hash is None:
        _password_hash = hash_password(PASSWORD)
    return _password_hash


@pytest_asyncio.fixture()
async def db():
    """Fresh in-memory schema per test; disposing the engine drops the DB."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture()
async def users(db) -> dict[str, User]:
    async with SessionLocal() as session:
        seeded = {
            "admin": User(name="Admin", email=ADMIN_EMAIL, password_hash=password_hash(), role=UserRole.admin),
            "operator": User(
                name="Operator", email=OPERATOR_EMAIL, password_hash=password_hash(), role=UserRole.operator
            ),
            "viewer": User(name="Viewer", email=VIEWER_EMAIL, password_hash=password_hash(), role=UserRole.viewer),
        }
        session.add_all(seeded.values())
        await session.commit()
        for user in seeded.values():
            await session.refresh(user)
    return seeded


@pytest_asyncio.fixture()
async def client(db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
def admin_headers(users) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(users['admin'])}"}


@pytest.fixture()
def viewer_headers(users) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(users['viewer'])}"}
