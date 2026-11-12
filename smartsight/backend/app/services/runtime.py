"""Process-wide runtime singletons wired up in the FastAPI lifespan."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import CameraConfig
from app.services.analysis import FrameAnalyzer
from app.services.camera.service import CameraService
from app.services.embedding.clip import ClipEmbedder
from app.services.indexing.video_indexer import VideoIndexer
from app.services.vectorstore import get_object_store, get_scene_store

logger = logging.getLogger(__name__)

_lock = threading.Lock()


@dataclass
class Runtime:
    embedder: ClipEmbedder
    analyzer: FrameAnalyzer
    camera: CameraService
    indexer: VideoIndexer


_runtime: Runtime | None = None


def ensure_camera_config() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        if db.get(CameraConfig, 1) is None:
            db.add(
                CameraConfig(
                    id=1,
                    stream_url=settings.stream_url_default,
                    live_fps=settings.live_fps_default,
                    index_interval_seconds=settings.live_index_interval_default,
                    detector_enabled=True,
                    auto_start=True,
                )
            )
            db.commit()
            logger.info("Created camera configuration (source: %s)", settings.stream_url_default)
    finally:
        db.close()


def init_runtime() -> Runtime:
    global _runtime
    with _lock:
        if _runtime is not None:
            return _runtime
        ensure_camera_config()
        embedder = ClipEmbedder()
        analyzer = FrameAnalyzer(embedder)
        camera = CameraService(analyzer)
        indexer = VideoIndexer(analyzer)
        indexer.start()
        indexer.recover_pending()
        _runtime = Runtime(embedder=embedder, analyzer=analyzer, camera=camera, indexer=indexer)

    db = SessionLocal()
    try:
        config = db.get(CameraConfig, 1)
        should_start = bool(config and config.auto_start and config.stream_url)
        stream_url = config.stream_url if config else ""
    finally:
        db.close()
    if should_start:
        try:
            _runtime.camera.start()
            logger.info("Auto-started camera monitoring (%s)", stream_url)
        except Exception as exc:  # noqa: BLE001 - monitoring failures must not block boot
            logger.warning("camera auto-start failed: %s", exc)
    return _runtime


def shutdown_runtime() -> None:
    global _runtime
    with _lock:
        runtime = _runtime
        _runtime = None
    if runtime is None:
        return
    runtime.camera.stop()
    runtime.indexer.stop()


def get_runtime() -> Runtime:
    if _runtime is None:
        return init_runtime()
    return _runtime


def ai_status() -> dict:
    from app.services.detection import yolo

    runtime = _runtime
    embedder = runtime.embedder if runtime else None
    detector = yolo.detector_status()
    try:
        scene_count = get_scene_store().count()
        object_count = get_object_store().count()
    except Exception:  # noqa: BLE001
        scene_count = object_count = 0
    return {
        "detector": detector,
        "embedder": {
            "model": embedder.model_name if embedder else get_settings().clip_model,
            "device": embedder.device if embedder else get_settings().clip_device,
            "loaded": bool(embedder and embedder.loaded),
            "dimension": int(getattr(embedder, "_dimension", 0) or 0),
        },
        "vector_store": {
            "backend": "chroma",
            "scenes": scene_count,
            "objects": object_count,
        },
    }
