"""Auth hardening: prod secret guard, media-token scoping, login rate limit."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_login_sets_http_only_cookie(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    cookie = r.headers.get("set-cookie", "")
    assert "fi_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "samesite=strict" in cookie


def test_logout_clears_cookie(client, admin_token):
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert "fi_session=" in r.headers.get("set-cookie", "")
    assert "Max-Age=0" in r.headers.get("set-cookie", "")


def test_me_works_via_cookie(client):
    """/auth/me must authenticate from the httpOnly cookie (SPA flow)."""
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    client.cookies.clear()
    client.cookies.set("fi_session", login.json()["access_token"])
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_media_token_is_scoped_and_short_lived(client, admin_token):
    from app.core.security import decode_media_token

    headers = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/auth/media-token", json={"path": "/api/streams/thumb/1_1.jpg"}, headers=headers)
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    payload = decode_media_token(token)
    assert payload is not None
    assert payload["kind"] == "media"
    assert payload["scope"] == "/api/streams/thumb/1_1.jpg"

    # A media token must NOT be accepted as a full access token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401

    # The full access token must NOT pass media-token validation
    assert decode_media_token(admin_token) is None

    # Non-media paths are rejected at minting
    r = client.post("/api/auth/media-token", json={"path": "/api/users"}, headers=headers)
    assert r.status_code == 400


def test_media_scope_mismatch_403(client, admin_token):
    from app.api.deps import require_media_scope
    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        user._media_scope = "/api/streams/thumb/other.jpg"  # type: ignore[attr-defined]
    finally:
        db.close()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        require_media_scope(user, "/api/streams/thumb/somewhere.jpg")
    assert exc.value.status_code == 403
    # Full-session users (no scope) are always allowed
    user._media_scope = None  # type: ignore[attr-defined]
    require_media_scope(user, "/api/streams/thumb/any.jpg")  # no raise


def test_production_secret_guard():
    """ENVIRONMENT=production + dev default secret must refuse to boot."""
    import os

    import pytest

    from app.core.config import get_settings

    get_settings.cache_clear()
    os.environ["ENVIRONMENT"] = "production"
    os.environ.pop("SECRET_KEY", None)  # falls back to the dev default
    with pytest.raises(RuntimeError, match="Refusing to start"):
        get_settings()
    get_settings.cache_clear()
    os.environ["ENVIRONMENT"] = "test"
    os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
    assert get_settings().environment == "test"
