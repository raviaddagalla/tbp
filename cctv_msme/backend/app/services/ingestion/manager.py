"""Background worker manager: owns all camera workers.

Runs independently of the request/response API cycle; started in the
FastAPI lifespan. Also implements the edge-aware load toggle: when many
cameras are running, effective sampling is throttled automatically.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Camera
from app.services.activity import event_hub
from app.services.activity_feed import record as record_activity
from app.services.ingestion.camera_worker import (
    CameraWorker,
    FILE_FINISHED_MSG,
    STATE_ONLINE,
)

logger = logging.getLogger(__name__)


class CameraWorkerManager:
    def __init__(self, embedder, vector_store, anomaly_checker=None, detector_factory=None):
        self.embedder = embedder
        self.vector_store = vector_store
        self.anomaly_checker = anomaly_checker
        self.detector_factory = detector_factory or _default_detector_factory()
        self.workers: dict[int, CameraWorker] = {}
        self.latest_buffers: dict = {}
        self._executor: ThreadPoolExecutor | None = None
        self._running = False

    # ------------------------------------------------------------ lifecycle
    def start_all(self) -> None:
        if self._running:
            return
        settings = get_settings()
        if not settings.worker_enabled:
            self._running = True  # mark running so ensure_worker() stays inert
            logger.info("Camera worker manager disabled (WORKER_ENABLED=false)")
            return
        self._executor = ThreadPoolExecutor(
            max_workers=max(2, settings.clip_inference_threads), thread_name_prefix="embed"
        )
        self._running = True
        db = SessionLocal()
        try:
            cameras = db.query(Camera).filter(Camera.is_active.is_(True)).all()
        finally:
            db.close()
        for cam in cameras:
            self.ensure_worker(cam.id)
        logger.info("Camera worker manager started (%d active cameras)", len(self.workers))

    def stop_all(self) -> None:
        self._running = False
        for worker in list(self.workers.values()):
            worker.stop()
        self.workers.clear()
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        logger.info("Camera worker manager stopped")

    # ------------------------------------------------------------ sync
    def ensure_worker(self, camera_id: int, force: bool = False) -> None:
        if not self._running or self._executor is None:
            return  # workers disabled on this machine
        db = SessionLocal()
        try:
            camera = db.get(Camera, camera_id)
            if camera is None:
                return
            worker = self.workers.get(camera_id)
            if not camera.is_active:
                if worker:
                    worker.stop()
                    self.workers.pop(camera_id, None)
                    record_activity("camera", f"Camera '{camera.name}' deactivated", camera_id)
                return
            # A fully-indexed upload must not be re-read from scratch on
            # every server boot (that would duplicate every vector row).
            if not force and (camera.rtsp_url or "").startswith("file://") and self._file_worker_finished(camera):
                if worker:
                    worker.stop()
                    self.workers.pop(camera_id, None)
                return
            if worker:
                worker.reload_config(camera)
                return
            worker = CameraWorker(
                camera=camera,
                embedder=self.embedder,
                vector_store=self.vector_store,
                latest_buffers=self.latest_buffers,
                executor=self._executor,
                anomaly_checker=self.anomaly_checker,
                on_status_change=self._on_status_change,
                detector_factory=self.detector_factory,
            )
            self.workers[camera_id] = worker
            worker.start()
        finally:
            db.close()

    def restart_worker(self, camera_id: int) -> None:
        """Stop an existing worker (if any) and start a fresh one (force)."""
        worker = self.workers.pop(camera_id, None)
        if worker:
            worker.stop()
        self.ensure_worker(camera_id, force=True)

    @staticmethod
    def _file_worker_finished(camera: Camera) -> bool:
        return camera.status == "offline" and camera.last_error == FILE_FINISHED_MSG

    def remove_camera(self, camera_id: int) -> None:
        worker = self.workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def _on_status_change(self, camera_id: int, prev: str, status: str, error: str) -> None:
        record_activity("camera", f"Camera {camera_id} is now {status}", camera_id)
        try:
            import asyncio

            loop = event_hub._lock._loop  # noqa: SLF001
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    event_hub.broadcast("camera_status", {"camera_id": camera_id, "status": status, "error": error}),
                    loop,
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ load / edge
    def active_count(self) -> int:
        return sum(1 for w in self.workers.values() if w.status == STATE_ONLINE)

    def queue_depth(self) -> int:
        return sum(getattr(w, "_inflight", 0) for w in self.workers.values())

    def effective_sample_interval(self) -> float:
        settings = get_settings()
        base = settings.frame_sample_interval_default
        if settings.edge_adaptive_load:
            n = max(1, self.active_count())
            if n >= 10:
                base = base * 4
            elif n >= 6:
                base = base * 2
            elif n >= 4:
                base = base * 1.5
        return round(max(0.1, base), 2)

    def status_map(self) -> dict[int, str]:
        return {cid: w.status for cid, w in self.workers.items()}


def _default_detector_factory():
    from app.services.detection.yolo import get_detector

    return get_detector
