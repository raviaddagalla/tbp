"""Background maintenance worker.

Runs on a simple cron-style thread (no APScheduler dependency):
  - nightly Chroma collection compaction (bounds HNSW tombstone bloat)
  - end-to-end retention cleanup (vector rows, thumbnails, tracklets)

Started/stopped from the FastAPI lifespan.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()
_last_compaction_day: str | None = None
_last_retention_run: float = 0.0


def start_maintenance_worker() -> None:
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_run, name="maintenance", daemon=True)
        _thread.start()
        logger.info("Maintenance worker started")


def stop_maintenance_worker() -> None:
    global _thread
    _stop.set()
    with _lock:
        if _thread and _thread.is_alive():
            _thread.join(timeout=5)
        _thread = None
    logger.info("Maintenance worker stopped")


def _run() -> None:
    global _last_compaction_day, _last_retention_run
    while not _stop.is_set():
        now = datetime.now(timezone.utc)
        try:
            from app.core.config import get_settings

            settings = get_settings()
        except Exception as exc:  # noqa: BLE001
            logger.warning("maintenance: settings unavailable: %s", exc)
            _stop.wait(60)
            continue

        today = now.strftime("%Y-%m-%d")
        if now.hour == settings.compaction_hour_utc and _last_compaction_day != today:
            _last_compaction_day = today
            _run_compaction()
            _last_retention_run = time.time()
            _run_retention(settings)
            _run_batch_reprocess(settings)

        # Retention also runs once per hour in case the compaction hour
        # is skipped while the host is down overnight.
        if time.time() - _last_retention_run >= 3600:
            _last_retention_run = time.time()
            _run_retention(settings)

        _stop.wait(120)


def _run_compaction() -> None:
    try:
        from app.services.vectorstore.factory import get_vector_store

        store = get_vector_store()
        compacted = store.compact()
        logger.info("Vector store compaction finished: %s", compacted or "no-op")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector store compaction failed: %s", exc)


def _run_batch_reprocess(settings) -> None:
    """Nightly offline pass: temporal windows over recorded footage (Phase 3)."""
    try:
        from app.services.ingestion.batch_reprocessor import run_batch_reprocess

        stats = run_batch_reprocess(settings)
        logger.info("Batch reprocess finished: %s", stats or "no cameras enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch reprocess failed: %s", exc)


def _run_retention(settings) -> None:
    """Delete vector rows, thumbnails and tracklets past each camera's
    retention window. Clip files are already cleaned by ClipRecorder."""
    try:
        from app.db.base import SessionLocal
        from app.db.models import Camera, Tracklet
        from app.services.vectorstore.factory import get_vector_store

        store = get_vector_store()
        db = SessionLocal()
        try:
            cameras = db.query(Camera).all()
        finally:
            db.close()

        for cam in cameras:
            cutoff = datetime.now(timezone.utc).timestamp() - cam.retention_hours * 3600
            try:
                store.delete(filters={"modality": "video", "camera_id": cam.id, "ts_epoch": {"$lte": cutoff}})
            except Exception as exc:  # noqa: BLE001
                logger.debug("[cam %s] vector retention delete failed: %s", cam.id, exc)
            # Object (detection) rows share the same retention window
            try:
                store.delete(filters={"modality": "object", "camera_id": cam.id, "ts_epoch": {"$lte": cutoff}})
            except Exception as exc:  # noqa: BLE001
                logger.debug("[cam %s] object row retention delete failed: %s", cam.id, exc)
            # Temporal (clip_event) rows share the same retention window
            try:
                store.delete(filters={"modality": "clip_event", "camera_id": cam.id, "ts_epoch": {"$lte": cutoff}})
            except Exception as exc:  # noqa: BLE001
                logger.debug("[cam %s] clip_event retention delete failed: %s", cam.id, exc)
            # Thumbnails
            try:
                from app.core.config import get_settings
                from app.services.media_storage import media_delete

                for f in settings.thumbs_dir.glob(f"{cam.id}_*"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            media_delete(f"thumbs/{f.name}")
                            npy = f.with_suffix(".npy")
                            if npy.exists():
                                npy.unlink(missing_ok=True)
                    except OSError:
                        continue
            except Exception as exc:  # noqa: BLE001
                logger.debug("thumb retention cleanup failed: %s", exc)
            # Tracklets
            try:
                cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
                db = SessionLocal()
                try:
                    db.query(Tracklet).filter(
                        Tracklet.camera_id == cam.id,
                        Tracklet.end_ts < cutoff_dt,
                    ).delete(synchronize_session=False)
                    db.commit()
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[cam %s] tracklet retention delete failed: %s", cam.id, exc)
        logger.info("Retention sweep complete (%d cameras)", len(cameras))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retention sweep failed: %s", exc)
