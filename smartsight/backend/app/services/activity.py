"""Activity feed persistence."""
from __future__ import annotations

import logging

from app.db.base import SessionLocal
from app.db.models import ActivityEvent
from app.utils import to_iso

logger = logging.getLogger(__name__)


def record(kind: str, message: str, recording_id: int | None = None) -> None:
    try:
        db = SessionLocal()
        try:
            db.add(ActivityEvent(kind=kind, message=message, recording_id=recording_id))
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - activity logging must never break work
        logger.warning("activity record failed: %s", exc)


def recent(limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(limit).all()
        return [
            {
                "id": row.id,
                "kind": row.kind,
                "message": row.message,
                "recording_id": row.recording_id,
                "created_at": to_iso(row.created_at),
            }
            for row in rows
        ]
    finally:
        db.close()
