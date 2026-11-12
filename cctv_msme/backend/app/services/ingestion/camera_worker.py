"""Per-camera ingestion worker.

Architecture: one capture thread per camera (OpenCV reads + clip recording
are blocking), feeding embedding jobs into a global threadpool so multiple
cameras never block the API event loop. Every failure is contained per
camera: a dropped RTSP stream triggers reconnect with exponential backoff,
and status transitions (online/offline/reconnecting) are persisted + pushed
over WebSocket.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable

import cv2
import numpy as np

from app.db.base import SessionLocal
from app.db.models import Camera
from app.services.activity_feed import record as record_activity
from app.services.ingestion.clip_recorder import ClipRecorder
from app.services.ingestion.sources import CameraSource, source_for
from app.utils.video import encode_jpeg, to_iso, utcnow

logger = logging.getLogger(__name__)

STATE_ONLINE = "online"
STATE_OFFLINE = "offline"
STATE_RECONNECTING = "reconnecting"

# Canonical "the upload finished indexing" marker (also used by the worker
# manager to avoid re-indexing a completed file on every server boot).
FILE_FINISHED_MSG = "File finished - indexing complete"
# File-source progress counters are flushed to the DB in batches (Postgres
# round-trips are the slow part for large uploads).
_FILE_DB_FLUSH_EVERY = 10


class CameraWorker:
    def __init__(
        self,
        camera: Camera,
        embedder,
        vector_store,
        latest_buffers: dict[int, "LatestFrameBuffer"],
        executor: ThreadPoolExecutor,
        anomaly_checker: Callable | None = None,
        on_status_change: Callable | None = None,
        detector_factory: Callable | None = None,
    ):
        self.camera = camera
        self.embedder = embedder
        self.vector_store = vector_store
        self.latest_buffers = latest_buffers
        self.executor = executor
        self.anomaly_checker = anomaly_checker
        self.on_status_change = on_status_change
        self.detector_factory = detector_factory
        self.detector = None
        self._detector_resolved = False
        self.tracker = None
        self._tracker_lock = threading.Lock()

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db_lock = threading.RLock()
        self._frame_buffer = self.latest_buffers.setdefault(camera.id, _LB())
        self._status = camera.status or STATE_OFFLINE
        self._last_status_write = 0.0
        self._last_db_sync = 0.0
        self._sample_seq = 0
        self._inflight = 0
        self._last_sample_ts = 0.0
        self._last_sample_vtime: float | None = None
        self._pending_progress = 0  # samples completed but not yet flushed to DB
        self._recorder: ClipRecorder | None = None
        self._prev_anomaly_ts = 0.0

        from app.services.vectorstore.base import VectorStore  # type guard

    # ------------------------------------------------------------ lifecycle
    @property
    def status(self) -> str:
        return self._status

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        cfg = self.camera
        self._is_file_source = (cfg.rtsp_url or "").startswith("file://")
        if not self._is_file_source:
            self._recorder = ClipRecorder(
                camera_id=cfg.id,
                clips_dir=cfg.clips_dir if hasattr(cfg, "clips_dir") else _clips_dir(),
                segment_seconds=cfg.clip_segment_seconds,
                retention_hours=cfg.retention_hours,
            )
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.camera.id}", daemon=True)
        self._thread.start()
        logger.info("Camera worker started for %s (id=%s)", self.camera.name, self.camera.id)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8)
        self._thread = None
        if self._recorder:
            try:
                self._recorder.close()
            except Exception:  # noqa: BLE001
                pass
            self._recorder = None
        logger.info("Camera worker stopped for %s", self.camera.name)

    def reload_config(self, camera: Camera) -> None:
        """Apply updated settings (interval/segment/retention) live."""
        self.camera = camera
        if self._recorder:
            self._recorder.segment_seconds = camera.clip_segment_seconds
            self._recorder.retention = timedelta(hours=camera.retention_hours)

    # ------------------------------------------------------------ capture loop
    def _run(self) -> None:
        camera = self.camera
        source = source_for(camera.rtsp_url, camera.name)
        self._source = source
        backoff = 2
        prev_connected_at = None

        try:
            while not self._stop.is_set():
                if not self._open_with_retry(source):
                    self._set_status(STATE_OFFLINE, "Could not open stream after retries")
                    return
                self._set_status(STATE_ONLINE, "")
                self._persist_health(force=True)
                connected_at = utcnow()
                self._db_update(lambda c: setattr(c, "connected_at", connected_at))

                idle_since = time.time()
                while not self._stop.is_set():
                    ok, frame = source.read()
                    if not ok:
                        if source.finished:
                            # Flush any batched progress so the DB reflects
                            # the real counts, then park the camera so it is
                            # not re-indexed from scratch on the next boot.
                            self._set_status(STATE_OFFLINE, FILE_FINISHED_MSG)
                            self._flush_progress(force=True)
                            with self._db_lock:
                                db = SessionLocal()
                                try:
                                    row = db.get(Camera, self.camera.id)
                                    if row:
                                        row.status = STATE_OFFLINE
                                        row.last_error = FILE_FINISHED_MSG
                                        db.commit()
                                finally:
                                    db.close()
                            record_activity("camera", f"Finished indexing footage '{camera.name}'")
                            return
                        self._set_status(STATE_RECONNECTING, "Stream dropped")
                        break
                    now = time.time()
                    # Short timeout guard for pathological blocking reads.
                    # Live sources only: file sources intentionally block on
                    # the embedding backpressure gate (the queue is the point),
                    # so a slow embedder must never look like a stalled stream.
                    if not getattr(self, "_is_file_source", False) and now - idle_since > 10:
                        self._set_status(STATE_RECONNECTING, "Stream stalled")
                        break
                    idle_since = now
                    self._ingest_frame(frame)

                source.release()
                self._set_status(STATE_RECONNECTING, "Reconnecting")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        finally:
            source.release()
            self._flush_progress(force=True)
            if self._recorder:
                try:
                    self._recorder.close()
                except Exception:  # noqa: BLE001
                    pass
            self._persist_health(force=True)

    def _open_with_retry(self, source: CameraSource) -> bool:
        attempts = 0
        while not self._stop.is_set():
            attempts += 1
            ok = source.open()
            if ok:
                return True
            self._set_status(STATE_RECONNECTING, f"Open failed (attempt {attempts})")
            self._persist_health()
            time.sleep(min(2 * attempts, 30))
        return False

    # ------------------------------------------------------------ frame path
    def _ingest_frame(self, frame_bgr: np.ndarray) -> None:
        if self._stop.is_set():
            return  # shutting down (reloader/restart): drop frames cleanly
        camera = self.camera
        now = utcnow()

        # 1. MJPEG preview buffer (throttled by caller cadence)
        preview_every = 1.0 / max(0.2, _preview_fps())
        prev = getattr(self, "_prev_preview_ts", 0.0)
        if time.time() - prev >= preview_every:
            try:
                self._frame_buffer.set(encode_jpeg(frame_bgr, quality=68))
            except Exception:  # noqa: BLE001
                pass
            self._prev_preview_ts = time.time()

        # 2. Rolling clip recorder (1 fps inside)
        segment_id = None
        if self._recorder:
            try:
                segment_id = self._recorder.write(frame_bgr, now)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cam %s] clip write error: %s", camera.id, exc)

        # 3. Sample for embedding at the configured interval (0.5s = 2 fps)
        interval = max(0.1, float(camera.sample_interval_seconds))
        sample_offset = 0.0
        if getattr(self, "_is_file_source", False):
            # Files are read at full speed, so pace by VIDEO time: sample when
            # the playback position advances by `interval` seconds (2 fps).
            src = getattr(self, "_source", None)
            vtime = src.position_seconds if src else 0.0
            last = getattr(self, "_last_sample_vtime", None)
            if last is not None and vtime - last < interval:
                return
            self._last_sample_vtime = vtime
            sample_offset = vtime
        else:
            elapsed = time.time() - getattr(self, "_last_sample_ts", 0.0)
            if elapsed < interval:
                return
            self._last_sample_ts = time.time()
        if getattr(self, "_inflight", 0) >= 16:
            if getattr(self, "_is_file_source", False):
                # Offline footage must never be dropped: block the read loop
                # until a slot frees instead of silently skipping frames
                # (files have no real-time requirement, so waiting is fine).
                while self._inflight >= 8 and not self._stop.is_set():
                    time.sleep(0.05)
                if self._stop.is_set():
                    return
            else:
                return  # live camera: drop rather than grow memory

        seq = self._sample_seq
        self._sample_seq += 1
        self._inflight = getattr(self, "_inflight", 0) + 1
        task = (frame_bgr, now, seq, segment_id, sample_offset)
        try:
            self.executor.submit(self._process_sample, task)
        except RuntimeError:
            # Executor already shut down (server stopping); drop the frame.
            self._inflight = max(0, getattr(self, "_inflight", 0) - 1)

    # ------------------------------------------------------------ embedding
    def _ensure_detector(self):
        """Resolve the object detector once per worker; degrades to no-op."""
        if self._detector_resolved:
            return self.detector
        self._detector_resolved = True
        if not self.detector_factory:
            self.detector = None
            return None
        try:
            self.detector = self.detector_factory()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] detector unavailable: %s", self.camera.id, exc)
            self.detector = None
        return self.detector

    def _ensure_tracker(self) -> None:
        if self.tracker is None:
            from app.services.detection.tracker import TrackletTracker

            interval = max(0.1, float(self.camera.sample_interval_seconds))
            self.tracker = TrackletTracker(
                camera_id=self.camera.id, persist=True, frame_rate=int(round(1.0 / interval))
            )

    def _process_sample(self, task) -> None:
        frame_bgr, ts, seq, segment_id, file_offset = task
        camera_id = self.camera.id
        try:
            embedding = self.embedder.embed_image(frame_bgr)
            thumb_name = f"{camera_id}_{int(ts.timestamp())}_{seq}.jpg"
            thumb_rel = f"thumbs/{thumb_name}"
            self._save_thumb(frame_bgr, thumb_name)

            if getattr(self, "_is_file_source", False):
                offset = round(float(file_offset or 0.0), 1)  # seconds into the file
            else:
                seg_start = (
                    self._recorder.segment_start(segment_id)
                    if (self._recorder and segment_id)
                    else None
                )
                offset = round(ts.timestamp() - seg_start, 1) if seg_start else 0.0

            meta = {
                "modality": "video",
                "camera_id": camera_id,
                "camera_name": self.camera.name,
                "zone": self.camera.zone,
                "timestamp": to_iso(ts),
                "ts_epoch": ts.timestamp(),
                "segment_id": segment_id or "",
                "thumbnail": thumb_rel,
                "clip_offset": offset,
                "file_source": bool(getattr(self, "_is_file_source", False)),
            }
            frame_id = str(uuid.uuid4())
            self.vector_store.add([frame_id], [embedding], [meta])

            self._index_objects(frame_bgr, ts, seq, segment_id, offset, frame_id, thumb_rel)

            self._bump_progress(ts)

            # Optional zero-shot safety anomaly check (stretch feature)
            if self.camera.anomaly_enabled and self.anomaly_checker:
                now_epoch = time.time()
                if now_epoch - self._prev_anomaly_ts >= _anomaly_interval():
                    self._prev_anomaly_ts = now_epoch
                    try:
                        self.anomaly_checker(self.camera, frame_bgr, ts, embedding, thumb_rel, segment_id, offset)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[cam %s] anomaly check failed: %s", camera_id, exc)
        except Exception as exc:  # noqa: BLE001 - never let one frame kill the pipeline
            logger.warning("[cam %s] sample processing failed: %s", camera_id, exc)
        finally:
            self._inflight = max(0, getattr(self, "_inflight", 0) - 1)

    # ------------------------------------------------------------ detection
    def _index_objects(
        self,
        frame_bgr: np.ndarray,
        ts: datetime,
        seq: int,
        segment_id: str,
        offset: float,
        frame_id: str,
        frame_thumb_rel: str,
    ) -> None:
        """Phase 1: run detection on the sampled frame, embed each crop, index
        object rows in the vector store and feed the per-camera tracker."""
        if not self.camera.detector_enabled:
            return
        detector = self._ensure_detector()
        if detector is None:
            return
        try:
            detections = detector.detect(frame_bgr)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] detection failed: %s", self.camera.id, exc)
            return
        if not detections:
            return

        with self._tracker_lock:
            self._ensure_tracker()

        camera_id = self.camera.id
        # Batch-embed every crop in ONE CLIP forward pass: on CPU this is
        # several times faster than one forward per detection.
        emb_by_index: list = [None] * len(detections)
        valid_idx = [i for i, d in enumerate(detections) if d.crop is not None and d.crop.size > 0]
        if valid_idx:
            try:
                batch_emb = self.embedder.embed_images_batch([detections[i].crop for i in valid_idx])
                for k, i in enumerate(valid_idx):
                    emb_by_index[i] = batch_emb[k]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cam %s] crop batch embedding failed: %s", camera_id, exc)

        attrs_by_index: list[dict] = [{}] * len(detections)
        for i in valid_idx:
            emb = emb_by_index[i]
            if emb is None:
                continue
            from app.services.detection.attributes import extract_attributes

            attrs_by_index[i] = extract_attributes(self.embedder, emb, detections[i].class_name)

        if not any(e is not None for e in emb_by_index):
            return
        # Tracker expects one (possibly empty) embedding per detection.
        emb_by_index = [e if e is not None else np.zeros(0, dtype=np.float32) for e in emb_by_index]

        reid_by_index: list[np.ndarray | None] = [None] * len(detections)
        if getattr(self.camera, "reid_enabled", False):
            try:
                from app.services.reid import get_reid_embedder

                person_idx = [i for i, d in enumerate(detections) if d.class_name == "person"]
                if person_idx:
                    reid_feats = get_reid_embedder().embed_people([detections[i].crop for i in person_idx])
                    if reid_feats.shape[1] == 512:
                        for k, i in enumerate(person_idx):
                            reid_by_index[i] = reid_feats[k]
            except Exception as exc:  # noqa: BLE001 - ReID is best-effort
                logger.warning("[cam %s] reid embedding failed: %s", camera_id, exc)

        try:
            _, _, tids = self.tracker.update(detections, ts, emb_by_index, attrs_by_index, reid_by_index)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[cam %s] tracker update failed: %s", camera_id, exc)
            tids = [0] * len(detections)

        h, w = frame_bgr.shape[:2]
        for i, det in enumerate(detections):
            emb = emb_by_index[i] if i < len(emb_by_index) else None
            if emb is None or emb.size == 0:
                continue  # crop could not be embedded; nothing to store
            try:
                crop_name = f"{camera_id}_{int(ts.timestamp())}_{seq}_o{det.class_id}_{i}.jpg"
                self._save_thumb(det.crop, crop_name)
                x1, y1, x2, y2 = det.xyxy
                meta = {
                    "modality": "object",
                    "camera_id": camera_id,
                    "camera_name": self.camera.name,
                    "zone": self.camera.zone,
                    "timestamp": to_iso(ts),
                    "ts_epoch": ts.timestamp(),
                    "segment_id": segment_id or "",
                    "clip_offset": offset,
                    "file_source": bool(getattr(self, "_is_file_source", False)),
                    "parent_frame_id": frame_id,
                    "object_class": det.class_name,
                    "bbox": f"{round(x1 / w, 4)},{round(y1 / h, 4)},{round(x2 / w, 4)},{round(y2 / h, 4)}",
                    "detection_confidence": round(det.confidence, 4),
                    "tracklet_local_id": tids[i] if i < len(tids) else 0,
                    "thumbnail": f"thumbs/{crop_name}",
                    "frame_thumbnail": frame_thumb_rel,
                    **attrs_by_index[i],
                }
                self.vector_store.add([str(uuid.uuid4())], [emb], [meta])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cam %s] object row add failed: %s", camera_id, exc)

    def _save_thumb(self, frame_bgr: np.ndarray, name: str) -> None:
        from app.core.config import get_settings
        from app.services.media_storage import media_put

        settings = get_settings()
        try:
            jpg = encode_jpeg(frame_bgr, quality=72, max_width=640)
            media_put(f"thumbs/{name}", jpg)
        except OSError as exc:
            logger.warning("thumb save failed: %s", exc)

    # ------------------------------------------------------------ helpers
    def _set_status(self, status: str, error: str) -> None:
        if self._status == status:
            return
        prev = self._status
        self._status = status
        self._last_error = error
        self._persist_health()
        if self.on_status_change:
            try:
                self.on_status_change(self.camera.id, prev, status, error)
            except Exception:  # noqa: BLE001
                pass

    def _bump_progress(self, ts: datetime) -> None:
        """Count a completed sample. File sources batch their DB writes
        (Postgres round-trips dominate); live sources write on a timer."""
        is_file = getattr(self, "_is_file_source", False)
        with self._db_lock:
            self._pending_progress += 1
            if not is_file:
                self._db_update(
                    lambda c: (
                        setattr(c, "frames_processed", c.frames_processed + 1),
                        setattr(c, "frames_indexed", c.frames_indexed + 1),
                        setattr(c, "last_seen_at", ts),
                    ),
                    throttle=5.0,
                )
            elif self._pending_progress >= _FILE_DB_FLUSH_EVERY:
                self._flush_progress(force=True, last_ts=ts)

    def _flush_progress(self, force: bool = False, last_ts: datetime | None = None) -> None:
        """Flush the batched sample counter into the camera row."""
        if (not force and self._pending_progress < _FILE_DB_FLUSH_EVERY) or self._pending_progress <= 0:
            return
        with self._db_lock:
            n = self._pending_progress
            self._pending_progress = 0
            db = SessionLocal()
            try:
                row = db.get(Camera, self.camera.id)
                if row:
                    row.frames_processed += n
                    row.frames_indexed += n
                    if last_ts is not None:
                        row.last_seen_at = last_ts
                    db.commit()
            except Exception as exc:  # noqa: BLE001 - progress is best-effort
                self._pending_progress += n  # keep the count; flush later
                logger.debug("progress flush failed: %s", exc)
            finally:
                db.close()

    def _db_update(self, fn, throttle: float = 0.0) -> None:
        with self._db_lock:
            now = time.time()
            if throttle and now - self._last_db_sync < throttle:
                return
            self._last_db_sync = now
            db = SessionLocal()
            try:
                row = db.get(Camera, self.camera.id)
                if row:
                    fn(row)
                    db.commit()
                    self.camera = row  # refresh local copy
            except Exception as exc:  # noqa: BLE001
                logger.debug("db update failed: %s", exc)
            finally:
                db.close()

    def _persist_health(self, force: bool = False) -> None:
        with self._db_lock:
            now = time.time()
            if not force and now - self._last_status_write < 3.0:
                return
            self._last_status_write = now
            db = SessionLocal()
            try:
                row = db.get(Camera, self.camera.id)
                if row:
                    row.status = self._status
                    row.last_error = getattr(self, "_last_error", "")
                    if self._status == STATE_ONLINE:
                        row.connected_at = row.connected_at or utcnow()
                    db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("health persist failed: %s", exc)
            finally:
                db.close()


class _LB:
    """Minimal LatestFrameBuffer to avoid circular imports."""

    def __init__(self) -> None:
        self._jpeg: bytes | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    def set(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._at = time.time()

    def get(self) -> tuple[bytes | None, float]:
        with self._lock:
            return self._jpeg, self._at


def _clips_dir():
    from app.core.config import get_settings

    return get_settings().clips_dir


def _preview_fps() -> float:
    from app.core.config import get_settings

    return get_settings().preview_fps


def _anomaly_interval() -> float:
    from app.core.config import get_settings

    return get_settings().anomaly_check_interval_seconds
