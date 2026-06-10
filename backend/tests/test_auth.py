from tests.conftest import ADMIN_EMAIL, PASSWORD


async def test_login_wrong_password(client, users):
    resp = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "nope-nope"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid email or password"}


async def test_login_unknown_email(client, users):
    resp = await client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert resp.status_code == 401


async def test_login_success_returns_tokens_and_user(client, users):
    resp = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == ADMIN_EMAIL
    assert body["user"]["role"] == "admin"
    # Refresh cookie is set for the auth path.
    assert "refresh_token" in resp.cookies

    # The access token works against a protected endpoint.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


async def test_refresh_with_body_token(client, users):
    login = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_protected_endpoint_requires_token(client, users):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401

async def test_login_accepts_reserved_domain_email(client, users):
    """The seeded admin may use e.g. admin@horus.local, which EmailStr rejects;
    login and the serialized user response must still work (regression)."""
    from app.models import User, UserRole
    from tests.conftest import SessionLocal, password_hash

    async with SessionLocal() as session:
        session.add(User(name="Local Admin", email="admin@horus.local",
                         password_hash=password_hash(), role=UserRole.admin))
        await session.commit()

    resp = await client.post("/api/v1/auth/login",
                             json={"email": "admin@horus.local", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "admin@horus.local"
