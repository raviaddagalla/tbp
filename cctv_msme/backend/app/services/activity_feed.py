"""Activity feed: persists events to SQLite and broadcasts over WebSocket."""
from __future__ import annotations

import logging
from typing import Any

from app.db.base import SessionLocal
from app.db.models import ActivityEvent
from app.services.activity import event_hub

logger = logging.getLogger(__name__)


def record(kind: str, message: str, camera_id: int | None = None) -> None:
    try:
        db = SessionLocal()
        try:
            ev = ActivityEvent(kind=kind, message=message, camera_id=camera_id)
            db.add(ev)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - activity logging must never crash the pipeline
        logger.warning("activity record failed: %s", exc)
        return

    payload: dict[str, Any] = {"kind": kind, "message": message, "camera_id": camera_id}
    try:
        import asyncio

        hub = event_hub
        if hub._lock._loop is not None and hub._lock._loop.is_running():  # noqa: SLF001
            asyncio.run_coroutine_threadsafe(hub.broadcast("activity", payload), hub._lock._loop)
    except Exception:  # noqa: BLE001
        pass


def recent(limit: int = 30) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(limit).all()
        )
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "message": r.message,
                "camera_id": r.camera_id,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()
