"""Uploaded video recordings: upload, list, progress, playback, delete."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import SessionLocal, get_db
from app.db.models import CameraConfig, Recording
from app.http_range import range_file_response
from app.services.activity import record as record_activity
from app.services.indexing.recordings import ALLOWED_EXTENSIONS, probe_video, purge_recording_data, recording_dict
from app.services.runtime import get_runtime
from app.utils import to_iso, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recordings", tags=["recordings"])


def _get_recording(db: Session, recording_id: int) -> Recording:
    recording = db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@router.get("")
def list_recordings(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Recording).order_by(Recording.id.desc()).all()
    return [recording_dict(row) for row in rows]


@router.get("/{recording_id}")
def get_recording(recording_id: int, db: Session = Depends(get_db)) -> dict:
    return recording_dict(_get_recording(db, recording_id))


@router.post("", status_code=201)
async def upload_recording(
    file: UploadFile = File(...),
    name: str = Form(""),
    sample_fps: float | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    original = file.filename or "video"
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    config = db.get(CameraConfig, 1)
    default_fps = float(config.default_sample_fps if config else settings.sample_fps_default)
    target_fps = float(sample_fps if sample_fps is not None else default_fps)
    if not (0.25 <= target_fps <= 10):
        raise HTTPException(status_code=400, detail="Sample FPS must be between 0.25 and 10")

    dest = Path(settings.recordings_dir) / f"{uuid.uuid4().hex}.{extension}"
    max_bytes = settings.video_upload_max_mb * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {settings.video_upload_max_mb} MB limit")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not store the upload: {exc}") from exc

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    info = await asyncio.to_thread(probe_video, dest)
    if not info.ok:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=info.error or "The file is not a readable video")

    recording = Recording(
        name=(name.strip() or original)[:200],
        original_name=original[:200],
        stored_name=dest.name,
        path=str(dest),
        status="queued",
        duration_seconds=info.duration_seconds,
        fps=info.fps,
        width=info.width,
        height=info.height,
        total_frames=info.total_frames,
        sample_fps=target_fps,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)
    record_activity("recording", f"Uploaded '{recording.name}' ({info.duration_seconds:.0f}s of footage)", recording.id)
    get_runtime().indexer.enqueue(recording.id)
    return recording_dict(recording)


@router.post("/{recording_id}/reindex")
def reindex_recording(recording_id: int, db: Session = Depends(get_db)) -> dict:
    recording = _get_recording(db, recording_id)
    state = get_runtime().indexer.state()
    if state["active"] == recording_id:
        raise HTTPException(status_code=409, detail="This recording is indexing right now")
    purge_recording_data(db, recording_id)
    recording.status = "queued"
    recording.error = ""
    recording.frames_indexed = 0
    recording.objects_detected = 0
    recording.frames_planned = 0
    recording.thumbnail = ""
    recording.completed_at = None
    db.commit()
    db.refresh(recording)
    record_activity("recording", f"Re-index queued for '{recording.name}'", recording.id)
    get_runtime().indexer.enqueue(recording_id)
    return recording_dict(recording)


@router.post("/{recording_id}/cancel")
def cancel_recording(recording_id: int, db: Session = Depends(get_db)) -> dict:
    recording = _get_recording(db, recording_id)
    runtime = get_runtime()
    state = runtime.indexer.state()
    if state["active"] != recording_id and recording_id not in state["queued"]:
        raise HTTPException(status_code=409, detail="This recording is not indexing")
    runtime.indexer.cancel(recording_id)
    if state["active"] != recording_id:
        # Still queued: it will be skipped by the worker; mark it now.
        db.refresh(recording)
        purge_recording_data(db, recording_id)
        recording.status = "cancelled"
        recording.frames_indexed = 0
        recording.objects_detected = 0
        recording.thumbnail = ""
        recording.completed_at = utcnow()
        db.commit()
    return {"ok": True, "cancelled": recording_id}


@router.delete("/{recording_id}")
def delete_recording(recording_id: int, db: Session = Depends(get_db)) -> dict:
    from app.services.indexing.recordings import delete_recording as delete_impl

    recording = _get_recording(db, recording_id)
    state = get_runtime().indexer.state()
    if state["active"] == recording_id:
        raise HTTPException(status_code=409, detail="Cancel indexing before deleting this recording")
    get_runtime().indexer.cancel(recording_id)
    name = recording.name
    path = Path(recording.path)
    purge_recording_data(db, recording_id)
    db.delete(recording)
    db.commit()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not delete %s: %s", path, exc)
    record_activity("recording", f"Deleted '{name}'")
    return {"ok": True, "deleted": recording_id}


@router.get("/{recording_id}/playback")
def playback(recording_id: int, request: Request, db: Session = Depends(get_db)):
    recording = _get_recording(db, recording_id)
    path = Path(recording.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The recording file is missing from disk")
    return range_file_response(path, request, media_type="video/mp4", filename=path.name)


@router.get("/{recording_id}/progress")
def progress(recording_id: int, db: Session = Depends(get_db)) -> dict:
    recording = _get_recording(db, recording_id)
    data = recording_dict(recording)
    state = get_runtime().indexer.state()
    data["indexer"] = {"active": state["active"], "queued": state["queued"]}
    return data
