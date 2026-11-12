"""Thin DB helpers used by the ingestion/alerts services (avoiding circular imports)."""
from __future__ import annotations

from datetime import datetime

from app.db.base import SessionLocal
from app.db.models import Alert, Camera


def save_alert(
    camera_id: int,
    camera_name: str,
    zone: str,
    alert_type: str,
    description: str,
    score: float,
    timestamp: datetime,
    thumbnail_path: str,
    segment_id: str,
    clip_offset: float,
) -> Alert:
    db = SessionLocal()
    try:
        alert = Alert(
            camera_id=camera_id,
            camera_name=camera_name,
            zone=zone,
            alert_type=alert_type,
            description=description,
            score=score,
            timestamp=timestamp,
            thumbnail_path=thumbnail_path,
            segment_id=segment_id,
            clip_offset=clip_offset,
        )
        db.add(alert)
        cam = db.get(Camera, camera_id)
        if cam:
            cam.alerts_count = (cam.alerts_count or 0) + 1
        db.commit()
        db.refresh(alert)
        return alert
    finally:
        db.close()
