CAMERA_PAYLOAD = {
    "name": "Front door",
    "protocol": "rtsp",
    "main_url": "rtsp://10.0.0.10:554/ch0",
    "sub_url": "rtsp://10.0.0.10:554/ch1",
    "username": "camuser",
    "password": "campass",
    "codec": "h265",
    "recording_mode": "motion",
}


async def test_camera_crud_as_admin(client, admin_headers):
    # Create
    resp = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    camera_id = created["id"]
    assert created["name"] == "Front door"
    # Credentials never leak through the public shape.
    assert "password" not in created
    assert "campass" not in resp.text

    # List
    resp = await client.get("/api/v1/cameras", headers=admin_headers)
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == camera_id

    # Get
    resp = await client.get(f"/api/v1/cameras/{camera_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["codec"] == "h265"

    # Update
    resp = await client.put(
        f"/api/v1/cameras/{camera_id}", json={"name": "Garage", "enabled": False}, headers=admin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Garage"
    assert body["enabled"] is False

    # Delete
    resp = await client.delete(f"/api/v1/cameras/{camera_id}", headers=admin_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/cameras/{camera_id}", headers=admin_headers)
    assert resp.status_code == 404


async def test_camera_write_forbidden_for_viewer(client, admin_headers, viewer_headers):
    resp = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=viewer_headers)
    assert resp.status_code == 403

    created = await client.post("/api/v1/cameras", json=CAMERA_PAYLOAD, headers=admin_headers)
    camera_id = created.json()["id"]

    resp = await client.put(f"/api/v1/cameras/{camera_id}", json={"name": "Hacked"}, headers=viewer_headers)
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/cameras/{camera_id}", headers=viewer_headers)
    assert resp.status_code == 403

    # Viewer without camera_permissions rows sees nothing (CONTRACTS.md §5).
    resp = await client.get("/api/v1/cameras", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    resp = await client.get(f"/api/v1/cameras/{camera_id}", headers=viewer_headers)
    assert resp.status_code == 403


async def test_camera_requires_auth(client, db):
    resp = await client.get("/api/v1/cameras")
    assert resp.status_code == 401
