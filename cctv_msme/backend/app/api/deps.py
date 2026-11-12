"""Auth dependencies: JWT bearer + role-based access control."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import SESSION_COOKIE, decode_access_token, decode_media_token
from app.db.base import get_db
from app.db.models import Camera, User

_bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"worker": 1, "supervisor": 2, "admin": 3}


def _unauthorized(detail: str = "Not authenticated"):
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden(detail: str = "Insufficient permissions"):
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _user_from_payload(payload: dict, db: Session) -> User:
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise _unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    raw = None
    if creds is not None:
        raw = creds.credentials
    elif request.cookies.get(SESSION_COOKIE):
        raw = request.cookies.get(SESSION_COOKIE)
    if raw is None:
        raise _unauthorized()
    payload = decode_access_token(raw)
    if not payload:
        raise _unauthorized("Invalid or expired token")
    if payload.get("kind") == "media":
        raise _unauthorized("Media tokens are not valid for this endpoint")
    return _user_from_payload(payload, db)


def get_current_user_query_token(
    request: Request,
    token: str | None = None,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Auth for media endpoints (<img>/<video>).

    Priority: Authorization header, then the httpOnly session cookie, then a
    short-lived `?token=` media token. Media tokens are scoped to a single
    resource; callers must call `require_media_scope(user, path)` afterwards.
    """
    if creds is not None:
        payload = decode_access_token(creds.credentials)
        if not payload:
            raise _unauthorized("Invalid or expired token")
        if payload.get("kind") == "media":
            user = _user_from_payload(payload, db)
            user._media_scope = payload.get("scope", "")  # type: ignore[attr-defined]
            return user
        return _user_from_payload(payload, db)
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        payload = decode_access_token(cookie)
        if not payload:
            raise _unauthorized("Invalid or expired token")
        if payload.get("kind") == "media":
            raise _unauthorized("Media tokens cannot be set as a cookie")
        return _user_from_payload(payload, db)
    if token:
        payload = decode_media_token(token)
        if payload is None:
            raise _unauthorized("Invalid or expired media token")
        user = _user_from_payload(payload, db)
        user._media_scope = payload.get("scope", "")  # type: ignore[attr-defined]
        return user
    raise _unauthorized()


def require_media_scope(user: User, expected_path: str) -> None:
    """403 unless the user authenticated via a full session or a media token
    whose scope covers the requested resource path (query strings ignored)."""
    scope = getattr(user, "_media_scope", None)  # type: ignore[attr-defined]
    if scope is None:
        return  # full bearer/cookie session
    if scope.split("?", 1)[0] != expected_path.split("?", 1)[0]:
        raise _forbidden("Media token is not scoped to this resource")


def require_media_scope_for_camera(user: User, camera_id: int, path: str) -> None:
    """Media-token scope check + zone enforcement for camera media."""
    require_media_scope(user, path)
    zone = getattr(user, "zone", None)
    if user.role in ("worker", "supervisor") and zone:
        from app.db.base import SessionLocal

        db = SessionLocal()
        try:
            cam = db.get(Camera, camera_id)
            if cam is None or cam.zone != zone:
                raise _forbidden("Camera is outside your zone")
        finally:
            db.close()


def require_roles(*roles: str):
    """Dependency factory: allow only listed roles."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise _forbidden(f"Requires role(s): {', '.join(roles)}")
        return user

    return dep


# ---------------------------------------------------------------------------
# Zone scoping
#
# worker/supervisor accounts with a non-null user.zone must never be able to
# read video, documents, alerts or summaries belonging to another zone.
# The server intersects client-supplied zone filters with the user's own zone
# and answers 403 when the client asks for zones outside their own (rather
# than silently returning a partial result).
# ---------------------------------------------------------------------------

def _zone_scoped(user: User) -> bool:
    return user.role in ("worker", "supervisor") and bool(user.zone)


def require_zone_scope(user: User, requested_zones: list[str] | None) -> list[str] | None:
    """Validate a client-supplied zone filter against the user's zone.

    Returns the effective zone filter to apply server-side:
      - admin / user without a zone  -> None (no restriction)
      - zone-restricted user, no zones requested -> [user.zone]
      - zone-restricted user, overlapping zones  -> the intersection
      - zone-restricted user, disjoint zones     -> raises 403
    """
    if not _zone_scoped(user):
        return None
    if not requested_zones:
        return [user.zone]
    requested = {z for z in requested_zones if z}
    if not requested:
        return [user.zone]
    allowed = requested & {user.zone}
    if not allowed:
        raise _forbidden(f"Access to zones outside '{user.zone}' is not permitted")
    return list(allowed)


def ensure_zone_access(user: User, zone: str) -> None:
    """403 unless the user may access the given (single) zone."""
    if not _zone_scoped(user):
        return
    if zone != user.zone:
        raise _forbidden(f"Access to zone '{zone}' is not permitted")


def ws_user_from_token(token: str | None) -> User | None:
    if not token:
        return None
    # Media tokens are accepted here too: the frontend cannot send the
    # httpOnly cookie on cross-origin WebSocket handshakes, so it authenticates
    # with a short-lived token scoped to /api/ws/events.
    payload = decode_access_token(token)
    if payload is None:
        payload = decode_media_token(token)
    if not payload:
        return None
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        user = db.get(User, int(payload["sub"]))
        return user if user and user.is_active else None
    finally:
        db.close()
