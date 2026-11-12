"""JWT auth helpers and password hashing (bcrypt)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"

# httpOnly session cookie used by the SPA (never readable from JS)
SESSION_COOKIE = "fi_session"
MEDIA_TOKEN_TTL_MINUTES = 5


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, username: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def create_media_token(user_id: int, role: str, username: str, scope: str) -> str:
    """Short-lived (5 min) token usable ONLY for the single resource in `scope`.

    Used by <img>/<video> tags that cannot send cookies/Authorization headers.
    The full-privilege access token is never exposed in query strings.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "username": username,
        "kind": "media",
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=MEDIA_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_media_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("kind") != "media":
        return None
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        return None
    # Enforce a hard 5-minute lifetime regardless of the exp claim.
    age = datetime.now(timezone.utc).timestamp() - float(iat)
    if age > MEDIA_TOKEN_TTL_MINUTES * 60:
        return None
    return payload
