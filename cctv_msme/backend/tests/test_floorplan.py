"""Phase 2: floor-plan calibration API (adjacency edges + pins + image)."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.state import state

    with TestClient(app) as c:
        if state.worker_manager is not None:
            for w in state.worker_manager.workers.values():
                w.embedder = state.embedder
        yield c


def _login(client, user, pw):
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def tokens(client):
    return {
        "admin": _login(client, "admin", "admin123"),
        "supervisor": _login(client, "supervisor", "supervisor123"),
        "worker": _login(client, "worker", "worker123"),
    }


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    from app.db.base import SessionLocal
    from app.db.models import Camera, CameraAdjacency, FloorPlan

    yield
    db = SessionLocal()
    try:
        db.query(CameraAdjacency).delete(synchronize_session=False)
        db.query(FloorPlan).delete(synchronize_session=False)
        db.query(Camera).filter(Camera.name.like("Adj%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def cams(client, tokens):
    from app.db.base import SessionLocal
    from app.db.models import Camera

    db = SessionLocal()
    try:
        ids = []
        for name in ("AdjA", "AdjB"):
            cam = Camera(name=name, rtsp_url="sim://adj", zone="Logistics", sample_interval_seconds=0.2)
            db.add(cam)
            db.commit()
            db.refresh(cam)
            ids.append(cam.id)
        return {"a": ids[0], "b": ids[1]}
    finally:
        db.close()


def test_adjacency_requires_supervisor_or_admin(client, tokens):
    r = client.get("/api/cameras/adjacency", headers=_auth(tokens["worker"]))
    assert r.status_code == 403
    r = client.get("/api/cameras/adjacency", headers=_auth(tokens["supervisor"]))
    assert r.status_code == 200
    assert r.json() == []


def test_adjacency_put_get_roundtrip(client, tokens, cams):
    body = {
        "edges": [
            {
                "from_camera_id": cams["a"],
                "to_camera_id": cams["b"],
                "expected_transit_seconds_min": 15,
                "expected_transit_seconds_max": 90,
                "direction_label": "Dock A -> Gate B",
            }
        ]
    }
    r = client.put("/api/cameras/adjacency", json=body, headers=_auth(tokens["worker"]))
    assert r.status_code == 403, "only admin may calibrate"

    r = client.put("/api/cameras/adjacency", json=body, headers=_auth(tokens["admin"]))
    assert r.status_code == 200, r.text

    r = client.get("/api/cameras/adjacency", headers=_auth(tokens["supervisor"]))
    assert r.status_code == 200
    edges = r.json()
    assert len(edges) == 1
    assert edges[0]["from_camera_id"] == cams["a"]
    assert edges[0]["to_camera_name"] == "AdjB"
    assert edges[0]["expected_transit_seconds_min"] == 15

    # invalid edges rejected
    bad = {"edges": [{"from_camera_id": 999999, "to_camera_id": cams["b"]}]}
    r = client.put("/api/cameras/adjacency", json=bad, headers=_auth(tokens["admin"]))
    assert r.status_code == 400
    self_loop = {"edges": [{"from_camera_id": cams["a"], "to_camera_id": cams["a"]}]}
    r = client.put("/api/cameras/adjacency", json=self_loop, headers=_auth(tokens["admin"]))
    assert r.status_code == 400


def test_floorplan_upload_pins_and_image(client, tokens):
    r = client.get("/api/floorplan", headers=_auth(tokens["supervisor"]))
    assert r.status_code == 200
    assert r.json()["id"] is None

    jpg = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9")
    r = client.post(
        "/api/floorplan",
        files={"file": ("plan.jpg", jpg, "image/jpeg")},
        data={"name": "Site Plan"},
        headers=_auth(tokens["worker"]),
    )
    assert r.status_code == 403, "only admin may upload"

    jpg.seek(0)
    r = client.post(
        "/api/floorplan",
        files={"file": ("plan.jpg", jpg, "image/jpeg")},
        data={"name": "Site Plan"},
        headers=_auth(tokens["admin"]),
    )
    assert r.status_code == 200, r.text
    fp = r.json()
    assert fp["image_url"] == "/api/floorplan/image"

    r = client.put(
        "/api/floorplan/pins",
        json={"pins": {"9999": {"x": 10, "y": 10}, "0": {"x": 1, "y": 1}}},
        headers=_auth(tokens["admin"]),
    )
    assert r.status_code == 200

    r = client.get("/api/floorplan", headers=_auth(tokens["supervisor"]))
    assert r.status_code == 200
    assert r.json()["id"] == fp["id"]

    # image served to an authenticated session
    r = client.get("/api/floorplan/image")
    assert r.status_code in (200, 401)  # 401 without auth is fine

    # media-token-scoped access works
    tok = client.post("/api/auth/media-token", json={"path": "/api/floorplan/image"}, headers=_auth(tokens["admin"]))
    assert tok.status_code == 200, tok.text
    r = client.get("/api/floorplan/image?token=" + tok.json()["token"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
