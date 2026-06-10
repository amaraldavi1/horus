from tests.test_cameras import CAMERA_PAYLOAD

TOKEN_HEADER = {"X-Internal-Token": "test-internal-token"}


async def test_internal_cameras_requires_token(client, db):
    resp = await client.get("/internal/cameras")
    assert resp.status_code == 401

    resp = await client.get("/internal/cameras", headers={"X-Internal-Token": "wrong-token"})
    assert resp.status_code == 401


async def test_internal_cameras_returns_decrypted_urls(client, admin_headers):
    created = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=admin_headers)
    assert created.status_code == 201

    resp = await client.get("/internal/cameras", headers=TOKEN_HEADER)
    assert resp.status_code == 200
    cameras = resp.json()
    assert len(cameras) == 1
    cam = cameras[0]
    # Internal shape carries full URLs with credentials injected (CONTRACTS.md §2).
    assert cam["main_url"] == "rtsp://camuser:campass@10.0.0.10:554/ch0"
    assert cam["sub_url"] == "rtsp://camuser:campass@10.0.0.10:554/ch1"
    assert cam["zones"] == []
    assert cam["schedule"] is None


async def test_internal_cameras_excludes_disabled(client, admin_headers):
    created = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=admin_headers)
    camera_id = created.json()["id"]
    await client.put(f"/api/v1/cameras/{camera_id}", json={"enabled": False}, headers=admin_headers)

    resp = await client.get("/internal/cameras", headers=TOKEN_HEADER)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_internal_recordings_fallback(client, admin_headers):
    created = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=admin_headers)
    camera_id = created.json()["id"]

    resp = await client.post(
        "/internal/recordings",
        headers=TOKEN_HEADER,
        json={
            "camera_id": camera_id,
            "path": f"/media/recordings/{camera_id}/2026-06-10/12-00-00.mp4",
            "started_at": "2026-06-10T12:00:00Z",
            "ended_at": "2026-06-10T12:00:30Z",
            "codec": "h265",
            "size_bytes": 5242880,
            "kind": "continuous",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["id"] > 0
