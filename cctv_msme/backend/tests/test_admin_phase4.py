"""Phase 4: diagnostics endpoint + signed update bundle verification."""
from __future__ import annotations

import base64
import hashlib

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


def test_diagnostics_requires_supervisor(client, tokens):
    r = client.get("/api/system/diagnostics", headers=_auth(tokens["worker"]))
    assert r.status_code == 403
    r = client.get("/api/system/diagnostics", headers=_auth(tokens["admin"]))
    assert r.status_code == 200


def test_diagnostics_shape(client, tokens):
    r = client.get("/api/system/diagnostics", headers=_auth(tokens["supervisor"]))
    assert r.status_code == 200
    body = r.json()
    assert "vector_store_backend" in body
    assert "queue_depth" in body
    assert "cameras" in body
    assert isinstance(body["cameras"], list)
    for cam in body["cameras"]:
        assert {"id", "name", "status", "frames_indexed", "inflight"} <= set(cam)
        assert "object_vectors" in cam


def test_updates_verify_requires_admin(client, tokens):
    r = client.post(
        "/api/admin/updates/verify",
        headers=_auth(tokens["supervisor"]),
        files={"bundle": ("x.fabupdate", b"data", "application/octet-stream")},
        data={"signature": "sig"},
    )
    assert r.status_code == 403


def test_updates_verify_unsigned_mode(client, tokens, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "update_public_key_path", "")
    r = client.post(
        "/api/admin/updates/verify",
        headers=_auth(tokens["admin"]),
        files={"bundle": ("x.fabupdate", b"data", "application/octet-stream")},
        data={"signature": "abc.def"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is False
    assert "unsigned mode" in body["detail"]


def test_updates_verify_valid_signature(client, tokens, tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.core.config import get_settings

    key = Ed25519PrivateKey.generate()
    pub_path = tmp_path / "public.pem"
    pub_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setattr(get_settings(), "update_public_key_path", str(pub_path))

    data = b"fake bundle"
    digest = hashlib.sha256(data).digest()
    sig = key.sign(digest)
    payload = base64.urlsafe_b64encode(sig).decode() + "." + base64.urlsafe_b64encode(digest).decode()

    r = client.post(
        "/api/admin/updates/verify",
        headers=_auth(tokens["admin"]),
        files={"bundle": ("rel.fabupdate", data, "application/octet-stream")},
        data={"signature": payload},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True, body
    assert body["detail"] == "signature valid"
    assert body["entries"] == []


def test_updates_verify_tampered(client, tokens, tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.core.config import get_settings

    key = Ed25519PrivateKey.generate()
    pub_path = tmp_path / "public.pem"
    pub_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setattr(get_settings(), "update_public_key_path", str(pub_path))

    data = b"fake bundle"
    digest = hashlib.sha256(data).digest()
    sig = key.sign(digest)
    payload = base64.urlsafe_b64encode(sig).decode() + "." + base64.urlsafe_b64encode(digest).decode()

    r = client.post(
        "/api/admin/updates/verify",
        headers=_auth(tokens["admin"]),
        files={"bundle": ("rel.fabupdate", data + b"tampered", "application/octet-stream")},
        data={"signature": payload},
    )
    assert r.status_code == 200
    assert r.json()["verified"] is False


def test_alert_dismiss(client, tokens):
    from app.db.base import SessionLocal
    from app.db.models import Alert, Camera

    db = SessionLocal()
    try:
        cam = db.query(Camera).first()
        cam_id = cam.id if cam else 1
        alert = Alert(
            camera_id=cam_id,
            camera_name="DismissCam",
            zone="General",
            alert_type="no_helmet",
            description="test dismiss",
            score=0.5,
            status="open",
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        aid = alert.id
    finally:
        db.close()

    try:
        r = client.post(f"/api/alerts/{aid}/dismiss", headers=_auth(tokens["admin"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "dismissed"
        assert r.json()["acknowledged_by"] == "admin"

        # already dismissed -> still dismissed
        r = client.post(f"/api/alerts/{aid}/dismiss", headers=_auth(tokens["admin"]))
        assert r.json()["status"] == "dismissed"
    finally:
        db = SessionLocal()
        try:
            db.query(Alert).filter(Alert.id == aid).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
