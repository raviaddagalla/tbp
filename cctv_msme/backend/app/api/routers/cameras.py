"""Camera management + health."""
from __future__ import annotations

import logging
import threading
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Camera, User
from app.schemas import CameraCreate, CameraHealthOut, CameraOut, CameraUpdate, MessageResponse
from app.services.activity_feed import record as record_activity
from app.state import state

router = APIRouter(prefix="/cameras", tags=["cameras"])

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    "mp4": "mp4",
    "m4v": "m4v",
    "mov": "mov",
    "avi": "avi",
    "mkv": "mkv",
    "webm": "webm",
}


def _scope_cameras(query, user: User):
    if user.role == "worker" and user.zone:
        return query.filter(Camera.zone == user.zone)
    return query


@router.get("", response_model=list[CameraOut])
def list_cameras(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cameras = _scope_cameras(db.query(Camera), user).order_by(Camera.id).all()
    return cameras


@router.post("", response_model=CameraOut)
def create_camera(
    body: CameraCreate,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    camera = Camera(**body.model_dump())
    if camera.sample_interval_seconds is None:
        camera.sample_interval_seconds = settings.frame_sample_interval_default
    if camera.detector_enabled is None:
        camera.detector_enabled = settings.detector_enabled_default
    if camera.reid_enabled is None:
        camera.reid_enabled = settings.reid_enabled_default
    if camera.batch_reprocess_enabled is None:
        camera.batch_reprocess_enabled = settings.batch_reprocess_enabled_default
    db.add(camera)
    db.commit()
    db.refresh(camera)
    record_activity("camera", f"Camera '{camera.name}' added ({camera.zone})", camera.id)
    state.worker_manager.ensure_worker(camera.id)
    return camera


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    body: CameraUpdate,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(camera, key, value)
    db.commit()
    db.refresh(camera)
    record_activity("camera", f"Camera '{camera.name}' updated", camera.id)
    state.worker_manager.ensure_worker(camera.id)
    return camera


@router.delete("/{camera_id}", response_model=MessageResponse)
def delete_camera(
    camera_id: int,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    name = camera.name
    state.worker_manager.remove_camera(camera.id)
    # Remove every trace of the camera so stitching/search never see orphans:
    # adjacency edges, tracklets (incl. ReID embeddings) and vector rows.
    from app.db.models import CameraAdjacency, Tracklet

    db.query(CameraAdjacency).filter(
        (CameraAdjacency.from_camera_id == camera_id) | (CameraAdjacency.to_camera_id == camera_id)
    ).delete(synchronize_session=False)
    db.query(Tracklet).filter(Tracklet.camera_id == camera_id).delete(synchronize_session=False)
    try:
        if state.vector_store is not None:
            state.vector_store.delete(filters={"camera_id": camera_id})
    except Exception:  # noqa: BLE001 - vector cleanup is best-effort
        pass
    db.delete(camera)
    db.commit()
    record_activity("camera", f"Camera '{name}' removed")
    return MessageResponse(message=f"Camera '{name}' deleted")


@router.post("/upload", response_model=CameraOut)
async def upload_video_footage(
    file: UploadFile = File(...),
    name: str = Form(...),
    zone: str = Form("General"),
    location_label: str = Form(""),
    anomaly_enabled: bool = Form(False),
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Upload a CCTV footage file; it is analysed at 2 fps like a live camera."""
    settings = get_settings()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported video type. Allowed: {', '.join(sorted(VIDEO_EXTENSIONS))}")

    max_bytes = settings.video_upload_max_mb * 1024 * 1024
    dest = settings.video_uploads_dir / f"{uuid.uuid4().hex}.{VIDEO_EXTENSIONS[ext]}"
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.video_upload_max_mb} MB limit")
            out.write(chunk)

    camera = Camera(
        name=name.strip() or file.filename,
        rtsp_url=f"file://{dest}",
        zone=zone,
        location_label=location_label,
        sample_interval_seconds=settings.frame_sample_interval_default,
        anomaly_enabled=anomaly_enabled,
        detector_enabled=settings.detector_enabled_default,
        reid_enabled=settings.reid_enabled_default,
        batch_reprocess_enabled=settings.batch_reprocess_enabled_default,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    # Mirror the footage to the shared bucket so other laptops can play it.
    try:
        from app.services.media_storage import media_put_file

        media_put_file(f"uploads/videos/{dest.name}", dest)
    except Exception:  # noqa: BLE001 - remote mirror is best-effort
        pass
    record_activity("camera", f"Footage '{camera.name}' uploaded for analysis ({zone})", camera.id)
    state.worker_manager.ensure_worker(camera.id)
    if camera.batch_reprocess_enabled:
        _trigger_reprocess(camera.id)
    return camera


@router.post("/{camera_id}/reprocess", response_model=MessageResponse)
def reprocess_camera_endpoint(
    camera_id: int,
    full: bool = Query(False),
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Kick off offline processing for one camera.

    Default: temporal window pooling over already-indexed frames (Phase 3).
    `full=1` on an uploaded footage camera instead wipes its existing
    vectors and re-reads the file from the start (fixes partial/duplicate
    indexing runs).
    """
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if full:
        if not (camera.rtsp_url or "").startswith("file://"):
            raise HTTPException(status_code=400, detail="full reprocess is only valid for uploaded footage (file://) cameras")
        _trigger_full_reindex(camera_id)
        return MessageResponse(message=f"Full re-index of '{camera.name}' started")
    if _trigger_reprocess(camera_id):
        return MessageResponse(message=f"Reprocessing footage from '{camera.name}' started")
    return MessageResponse(message=f"Reprocessing for '{camera.name}' queued (already running)")


def _trigger_full_reindex(camera_id: int) -> None:
    """Wipe the camera's vectors + counters and restart its worker (force)."""

    def _run() -> None:
        try:
            from app.core.config import get_settings
            from app.db.base import SessionLocal
            from app.db.models import Camera, Tracklet
            from app.services.vectorstore.factory import get_vector_store

            settings = get_settings()
            store = get_vector_store()
            from app.state import state

            # Stop any worker that is (re)reading the file right now.
            existing = state.worker_manager.workers.get(camera_id)
            if existing:
                existing.stop()
                state.worker_manager.workers.pop(camera_id, None)

            db = SessionLocal()
            try:
                cam = db.get(Camera, camera_id)
                if not cam:
                    return
                store.delete(filters={"camera_id": camera_id})
                db.query(Tracklet).filter(Tracklet.camera_id == camera_id).delete(synchronize_session=False)
                cam.frames_indexed = 0
                cam.frames_processed = 0
                cam.status = "offline"
                cam.last_error = ""
                cam.connected_at = None
                cam.last_seen_at = None
                db.commit()
                db.refresh(cam)
            finally:
                db.close()
            state.worker_manager.ensure_worker(camera_id, force=True)
            record_activity("camera", f"Full re-index started for '{cam.name}'")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] full re-index failed: %s", camera_id, exc)

    threading.Thread(target=_run, name=f"reindex-{camera_id}", daemon=True).start()


def _trigger_reprocess(camera_id: int) -> bool:
    from app.services.ingestion.batch_reprocessor import reprocess_camera

    def _run() -> None:
        try:
            from app.core.config import get_settings
            from app.db.base import SessionLocal
            from app.db.models import Camera
            from app.services.vectorstore.factory import get_vector_store

            settings = get_settings()
            store = get_vector_store()
            db = SessionLocal()
            try:
                cam = db.get(Camera, camera_id)
                if not cam:
                    return
                stats = reprocess_camera(db, store, cam, settings)
                record_activity("camera", f"Reprocessing finished for '{cam.name}' (+{stats['windows_added']} temporal windows)")
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] background reprocess failed: %s", camera_id, exc)

    threading.Thread(target=_run, name=f"reprocess-{camera_id}", daemon=True).start()
    return True


@router.get("/{camera_id}/health", response_model=CameraHealthOut)
def camera_health(
    camera_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    duration = 0.0
    if (camera.rtsp_url or "").startswith("file://"):
        try:
            from app.services.ingestion.sources import source_for

            src = source_for(camera.rtsp_url, camera.name)
            src.open()
            duration = src.duration_seconds
            src.release()
        except Exception:  # noqa: BLE001 - progress info is best-effort
            pass
    return CameraHealthOut(
        camera_id=camera.id,
        status=camera.status,
        frames_indexed=camera.frames_indexed,
        frames_processed=camera.frames_processed,
        last_seen_at=camera.last_seen_at,
        file_duration_seconds=round(duration, 1),
        file_indexed_seconds=round(camera.frames_indexed * camera.sample_interval_seconds, 1),
    )
