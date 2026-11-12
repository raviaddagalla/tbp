"""Auth routes."""
# NOTE: do NOT add `from __future__ import annotations` here — it breaks
# slowapi's route decoration with FastAPI's typed-signature analysis.

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    SESSION_COOKIE,
    create_access_token,
    create_media_token,
    verify_password,
)
from app.db.base import get_db
from app.db.models import User
from app.schemas import LoginRequest, MessageResponse, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

limiter = Limiter(key_func=get_remote_address, default_limits=[])

_MEDIA_PATH_PREFIXES = (
    "/api/streams/preview/",
    "/api/streams/snapshot/",
    "/api/streams/thumb/",
    "/api/streams/clip/",
    "/api/streams/file/",
    "/api/floorplan/image",
    "/api/ws/events",
)


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="strict",
        secure=settings.environment == "production",
        path="/",
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
def login(request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token(user.id, user.role, user.username)
    _set_session_cookie(response, token)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", response_model=MessageResponse)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/media-token")
def media_token(body: dict, user: User = Depends(get_current_user)):
    """Mint a 5-minute, single-resource token for <img>/<video> tags."""
    path = (body.get("path") or "").strip()
    if not path.startswith(_MEDIA_PATH_PREFIXES):
        raise HTTPException(status_code=400, detail="Only media stream paths are allowed")
    return {
        "token": create_media_token(user.id, user.role, user.username, path),
        "expires_in": 300,
    }


@router.post("/me/password", response_model=MessageResponse)
def change_password(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    old = body.get("old_password", "")
    new = body.get("new_password", "")
    if not verify_password(old, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    from app.core.security import hash_password

    user.hashed_password = hash_password(new)
    db.commit()
    return MessageResponse(message="Password updated")
