"""Dashboard aggregates: totals, recent detections, storage, AI status."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CameraConfig, Detection, Frame, Recording
from app.media import directory_size, human_bytes
from app.services.activity import recent as recent_activity
from app.services.runtime import ai_status
from app.utils import to_iso

logger = logging.getLogger(__name__)


def recent_detections(limit: int = 8, object_class: str | None = None, source_type: str | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        query = (
            db.query(Detection, Frame, Recording)
            .join(Frame, Detection.frame_id == Frame.id)
            .outerjoin(Recording, Frame.recording_id == Recording.id)
        )
        if object_class:
            query = query.filter(Detection.object_class == object_class)
        if source_type:
            query = query.filter(Detection.source_type == source_type)
        rows = query.order_by(Detection.captured_at.desc(), Detection.id.desc()).limit(limit).all()
        out = []
        for detection, frame, recording in rows:
            out.append(
                {
                    "id": detection.id,
                    "object_class": detection.object_class,
                    "confidence": round(detection.confidence, 3),
                    "track_id": detection.track_id,
                    "colour": detection.attributes,
                    "bbox": [detection.x1, detection.y1, detection.x2, detection.y2],
                    "thumbnail_url": f"/api/media/thumb/{detection.thumbnail}" if detection.thumbnail else "",
                    "frame_thumbnail_url": f"/api/media/thumb/{frame.thumbnail}" if frame.thumbnail else "",
                    "captured_at": to_iso(detection.captured_at),
                    "timestamp_seconds": detection.timestamp_seconds,
                    "source_type": detection.source_type,
                    "recording_id": frame.recording_id,
                    "recording_name": recording.name if recording else "ESP32 Live camera",
                    "frame_id": frame.id,
                    "playback_url": f"/api/recordings/{frame.recording_id}/playback" if frame.recording_id else "",
                }
            )
        return out
    finally:
        db.close()


def activity_feed(limit: int = 20) -> list[dict]:
    return recent_activity(limit)


def counts() -> dict:
    db = SessionLocal()
    try:
        frames_total = db.query(func.count(Frame.id)).scalar() or 0
        live_frames = db.query(func.count(Frame.id)).filter(Frame.source_type == "live").scalar() or 0
        upload_frames = frames_total - live_frames
        detections_total = db.query(func.count(Detection.id)).scalar() or 0
        recordings_total = db.query(func.count(Recording.id)).scalar() or 0
        recordings_ready = db.query(func.count(Recording.id)).filter(Recording.status == "ready").scalar() or 0
        recordings_indexing = (
            db.query(func.count(Recording.id)).filter(Recording.status.in_(("queued", "processing"))).scalar() or 0
        )
        class_rows = (
            db.query(Detection.object_class, func.count(Detection.id))
            .group_by(Detection.object_class)
            .order_by(func.count(Detection.id).desc())
            .limit(8)
            .all()
        )
        indexing_seconds = db.query(func.sum(Recording.duration_seconds)).scalar() or 0.0
        return {
            "frames_total": int(frames_total),
            "live_frames": int(live_frames),
            "upload_frames": int(upload_frames),
            "detections_total": int(detections_total),
            "recordings_total": int(recordings_total),
            "recordings_ready": int(recordings_ready),
            "recordings_indexing": int(recordings_indexing),
            "indexed_video_seconds": round(float(indexing_seconds), 1),
            "object_classes": [{"object_class": name, "count": int(count)} for name, count in class_rows],
        }
    finally:
        db.close()


def storage_status() -> dict:
    settings = get_settings()
    db_path = settings.data_dir / "smartsight.db"
    database_bytes = db_path.stat().st_size if db_path.is_file() else 0
    thumbs_bytes, thumbs_files = directory_size(settings.thumbs_dir)
    snapshots_bytes, snapshots_files = directory_size(settings.snapshots_dir)
    recordings_bytes = 0
    recordings_files = 0
    recordings_dir = Path(settings.recordings_dir)
    if recordings_dir.exists():
        for item in recordings_dir.glob("*"):
            if item.is_file():
                try:
                    recordings_bytes += item.stat().st_size
                    recordings_files += 1
                except OSError:
                    continue
    vector_bytes, _ = directory_size(Path(settings.chroma_dir))
    return {
        "data_dir": str(settings.data_dir),
        "database": {"bytes": database_bytes, "human": human_bytes(database_bytes)},
        "thumbnails": {"bytes": thumbs_bytes, "count": thumbs_files, "human": human_bytes(thumbs_bytes)},
        "snapshots": {"bytes": snapshots_bytes, "count": snapshots_files, "human": human_bytes(snapshots_bytes)},
        "recordings": {"bytes": recordings_bytes, "count": recordings_files, "human": human_bytes(recordings_bytes)},
        "vectorstore": {"bytes": vector_bytes, "human": human_bytes(vector_bytes)},
        "max_upload_mb": settings.video_upload_max_mb,
        "index_frame_cap": settings.video_index_max_frames,
    }


def camera_row() -> dict:
    db = SessionLocal()
    try:
        row = db.get(CameraConfig, 1)
        if row is None:
            return {}
        return {
            "stream_url": row.stream_url,
            "live_fps": row.live_fps,
            "index_interval_seconds": row.index_interval_seconds,
            "detector_enabled": row.detector_enabled,
            "auto_start": row.auto_start,
            "default_sample_fps": row.default_sample_fps,
            "status": row.status,
            "last_error": row.last_error,
            "last_frame_at": to_iso(row.last_frame_at),
            "frames_received": row.frames_received,
            "frames_indexed": row.frames_indexed,
            "objects_detected": row.objects_detected,
        }
    finally:
        db.close()


def overview() -> dict:
    from app.services.runtime import get_runtime

    runtime = get_runtime()
    return {
        "totals": counts(),
        "camera": runtime.camera.stats(),
        "camera_config": camera_row(),
        "ai": ai_status(),
        "storage": storage_status(),
        "recent_detections": recent_detections(8),
        "activity": activity_feed(12),
    }
