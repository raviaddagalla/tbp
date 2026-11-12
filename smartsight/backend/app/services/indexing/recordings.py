"""Recording helpers: probing, serialising, purging."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Detection, Frame, Recording
from app.services.vectorstore import get_object_store, get_scene_store
from app.utils import to_iso

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}


@dataclass
class VideoInfo:
    ok: bool
    duration_seconds: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    total_frames: int = 0
    error: str = ""


def probe_video(path: str | Path) -> VideoInfo:
    path = Path(path)
    if not path.is_file():
        return VideoInfo(False, error="File not found")
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        if not capture.isOpened():
            return VideoInfo(False, error="Unsupported or corrupt video file")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = total / fps if fps > 0 and total > 0 else 0.0
        return VideoInfo(True, round(duration, 3), round(fps, 3), width, height, total)
    finally:
        capture.release()


def recording_dict(recording: Recording) -> dict:
    progress = 0.0
    if recording.frames_planned > 0:
        progress = min(100.0, 100.0 * recording.frames_indexed / recording.frames_planned)
    elif recording.status == "ready":
        progress = 100.0
    return {
        "id": recording.id,
        "name": recording.name,
        "original_name": recording.original_name,
        "status": recording.status,
        "error": recording.error,
        "duration_seconds": round(recording.duration_seconds, 2),
        "fps": recording.fps,
        "width": recording.width,
        "height": recording.height,
        "total_frames": recording.total_frames,
        "sample_fps": recording.sample_fps,
        "frames_indexed": recording.frames_indexed,
        "frames_planned": recording.frames_planned,
        "objects_detected": recording.objects_detected,
        "progress": round(progress, 1),
        "thumbnail_url": f"/api/media/thumb/{recording.thumbnail}" if recording.thumbnail else "",
        "playback_url": f"/api/recordings/{recording.id}/playback",
        "created_at": to_iso(recording.created_at),
        "completed_at": to_iso(recording.completed_at),
    }


def purge_recording_data(db, recording_id: int, delete_files: bool = True) -> int:
    """Delete frames/detections (+ thumbnails) and vectors for one recording."""
    frames = db.query(Frame).filter(Frame.recording_id == recording_id).all()
    thumb_names: list[str] = []
    for frame in frames:
        if frame.thumbnail:
            thumb_names.append(frame.thumbnail)
    detections = db.query(Detection).filter(Detection.recording_id == recording_id).all()
    for det in detections:
        if det.thumbnail:
            thumb_names.append(det.thumbnail)

    db.query(Detection).filter(Detection.recording_id == recording_id).delete(synchronize_session=False)
    db.query(Frame).filter(Frame.recording_id == recording_id).delete(synchronize_session=False)
    db.commit()

    try:
        get_scene_store().delete(filters={"recording_id": recording_id})
        get_object_store().delete(filters={"recording_id": recording_id})
    except Exception as exc:  # noqa: BLE001 - vector cleanup is best-effort
        logger.warning("vector purge failed for recording %s: %s", recording_id, exc)

    if delete_files:
        thumbs_dir = get_settings().thumbs_dir
        for name in set(thumb_names):
            try:
                (thumbs_dir / Path(name).name).unlink(missing_ok=True)
            except OSError:
                pass
    return len(frames)


def delete_recording(recording_id: int) -> bool:
    db = SessionLocal()
    try:
        recording = db.get(Recording, recording_id)
        if recording is None:
            return False
        purge_recording_data(db, recording_id)
        path = Path(recording.path)
        db.delete(recording)
        db.commit()
        if path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("could not delete recording file %s: %s", path, exc)
        return True
    finally:
        db.close()
