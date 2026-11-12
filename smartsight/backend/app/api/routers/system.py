"""Overview, activity feed, frame detail and settings."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import CameraConfig
from app.schemas import CameraConfigUpdate
from app.services.overview import camera_row, counts, overview, recent_detections, storage_status
from app.services.runtime import ai_status, get_runtime
from app.services.search import frame_detail

router = APIRouter(tags=["system"])


@router.get("/overview")
def get_overview() -> dict:
    return overview()


@router.get("/activity")
def get_activity(
    limit: int = Query(40, ge=1, le=200),
    object_class: str | None = Query(None),
    source_type: str | None = Query(None, pattern="^(live|upload)$"),
) -> dict:
    totals = counts()
    return {
        "items": recent_detections(limit, object_class=object_class, source_type=source_type),
        "classes": totals["object_classes"],
    }


@router.get("/frames/{frame_id}")
def get_frame(frame_id: int) -> dict:
    detail = frame_detail(frame_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    return detail


def _settings_payload() -> dict:
    settings = get_settings()
    runtime = get_runtime()
    return {
        "camera": camera_row(),
        "camera_runtime": runtime.camera.stats(),
        "indexing": {
            "default_sample_fps": camera_row().get("default_sample_fps", settings.sample_fps_default),
            "max_frames": settings.video_index_max_frames,
            "max_upload_mb": settings.video_upload_max_mb,
            "thumbnail_max_width": settings.thumbnail_max_width,
        },
        "ai": ai_status(),
        "storage": storage_status(),
        "server": {
            "app_name": settings.app_name,
            "data_dir": str(settings.data_dir),
            "vector_store_dir": settings.chroma_dir,
            "indexer": runtime.indexer.state(),
        },
    }


@router.get("/settings")
def get_settings_payload() -> dict:
    return _settings_payload()


@router.put("/settings")
async def update_settings(body: CameraConfigUpdate, db: Session = Depends(get_db)) -> dict:
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return _settings_payload()

    if "stream_url" in updates and updates["stream_url"]:
        raw_url = updates["stream_url"].strip()
        if raw_url and not raw_url.startswith(("http://", "https://", "rtsp://", "rtmp://", "sim://")):
            raw_url = f"http://{raw_url}"
        updates["stream_url"] = raw_url

    runtime = get_runtime()
    was_running = runtime.camera.running
    needs_restart = was_running and any(
        key in updates for key in ("stream_url", "live_fps", "index_interval_seconds", "auto_start")
    )
    if needs_restart:
        await asyncio.to_thread(runtime.camera.stop)

    config = db.get(CameraConfig, 1)
    if config is None:
        config = CameraConfig(id=1)
        db.add(config)
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)
    db.commit()
    db.refresh(config)
    runtime.camera.update_config(**updates)

    if needs_restart:
        await asyncio.to_thread(runtime.camera.start)

    return _settings_payload()
