"""Single ESP32-CAM monitoring service.

Owns one capture thread: reads frames, runs detection + ByteTrack for the live
overlay, and samples frames for CLIP indexing on a separate single-worker
executor so embedding never stalls the preview.

Connection failures are contained: the source is reopened with exponential
backoff and the status (`connecting`, `online`, `reconnecting`, `error`) is
persisted for the UI. No RTSP assumptions are made — the configured URL decides
which reader is used (see `sources.py`).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np

from app.db.base import SessionLocal
from app.db.models import CameraConfig
from app.media import annotate, encode_jpeg, save_snapshot
from app.services.analysis import FrameAnalyzer, FrameContext
from app.services.camera.sources import build_source
from app.services.detection.tracker import ObjectTracker
from app.utils import to_iso, utcnow

logger = logging.getLogger(__name__)


class LatestFrameBuffer:
    """Thread-safe holder for the most recent JPEG."""

    def __init__(self) -> None:
        self._jpeg: bytes | None = None
        self._updated_at = 0.0
        self._lock = threading.Lock()

    def set(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._updated_at = time.time()

    def get(self) -> tuple[bytes | None, float]:
        with self._lock:
            return self._jpeg, self._updated_at


class CameraService:
    def __init__(self, analyzer: FrameAnalyzer):
        self.analyzer = analyzer
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-index")
        self._state_lock = threading.RLock()

        self._annotated = LatestFrameBuffer()
        self._raw = LatestFrameBuffer()
        self._detections: list[dict] = []
        self._last_raw_frame: np.ndarray | None = None
        self._frame_width = 0
        self._frame_height = 0
        self._measured_fps = 0.0
        self._last_frame_at: datetime | None = None
        self._source_kind = "unknown"
        self._source_label = ""

        self._status = "offline"
        self._last_error = ""
        self._frames_received = 0
        self._frames_indexed = 0
        self._objects_detected = 0
        self._live_frame_number = 0
        self._index_pending = False
        self._last_index_at = 0.0
        self._last_persist_at = 0.0
        self._config: dict = {}

    # ------------------------------------------------------------- lifecycle
    def start(self) -> dict:
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                return {"started": True, "already_running": True}
            self._load_config()
            self._stop.clear()
            self._status = "connecting"
            self._last_error = ""
            self._persist(force=True)
            self._thread = threading.Thread(target=self._run, name="esp32-camera", daemon=True)
            self._thread.start()
        logger.info("Camera monitoring started (%s)", self._config.get("stream_url"))
        return {"started": True, "already_running": False}

    def stop(self) -> dict:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=8)
        self._thread = None
        self._status = "offline"
        self._detections = []
        self._persist(force=True)
        logger.info("Camera monitoring stopped")
        return {"stopped": True, "running": False}

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --------------------------------------------------------------- config
    def _load_config(self) -> None:
        db = SessionLocal()
        try:
            row = db.get(CameraConfig, 1)
            if row is None:
                row = CameraConfig(id=1)
                db.add(row)
                db.commit()
                db.refresh(row)
            self._config = {
                "stream_url": row.stream_url,
                "live_fps": max(0.5, float(row.live_fps or 2.0)),
                "index_interval_seconds": max(1.0, float(row.index_interval_seconds or 3.0)),
                "detector_enabled": bool(row.detector_enabled),
            }
            self._status = row.status or "offline"
            self._frames_received = row.frames_received or 0
            self._frames_indexed = row.frames_indexed or 0
            self._objects_detected = row.objects_detected or 0
        finally:
            db.close()

    def update_config(self, **values) -> dict:
        db = SessionLocal()
        try:
            row = db.get(CameraConfig, 1)
            if row is None:
                row = CameraConfig(id=1)
                db.add(row)
            for key, value in values.items():
                if value is not None and hasattr(row, key):
                    setattr(row, key, value)
            db.commit()
            db.refresh(row)
            config = {
                "stream_url": row.stream_url,
                "live_fps": row.live_fps,
                "index_interval_seconds": row.index_interval_seconds,
                "detector_enabled": row.detector_enabled,
            }
        finally:
            db.close()
        self._config = {**self._config, **config}
        return config

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        source = build_source(self._config.get("stream_url", "sim://demo"))
        self._source_kind = source.kind
        self._source_label = getattr(source, "label", "")
        opened = False
        failures = 0
        backoff = 1.0
        live_fps = max(0.5, float(self._config.get("live_fps", 2.0)))
        interval = 1.0 / live_fps
        index_interval = max(1.0, float(self._config.get("index_interval_seconds", 3.0)))
        tracker = ObjectTracker(frame_rate=max(1, int(round(live_fps))))
        last_processed = 0.0

        try:
            while not self._stop.is_set():
                if not opened:
                    self._set_status("connecting" if failures == 0 else "reconnecting")
                    opened = source.open()
                    if not opened:
                        failures += 1
                        self._last_error = f"Could not connect to {self._config.get('stream_url')}"
                        self._set_status("reconnecting")
                        self._persist(force=True)
                        self._sleep(backoff)
                        backoff = min(backoff * 1.7, 30.0)
                        continue
                    self._source_kind = source.kind
                    self._source_label = getattr(source, "label", "")
                    failures = 0
                    backoff = 1.0
                    self._last_error = ""
                    self._set_status("online")
                    self._persist(force=True)

                ok, frame = source.read()
                if not ok or frame is None:
                    # Stalled / dropped stream: reconnect rather than hang.
                    self._set_status("reconnecting")
                    self._last_error = "Camera stream dropped or stalled"
                    self._persist(force=True)
                    source.release()
                    opened = False
                    self._sleep(min(backoff, 5.0))
                    backoff = min(backoff * 1.7, 30.0)
                    continue

                now = time.monotonic()
                if now - last_processed < interval:
                    continue  # consume the frame, keep the display cadence light
                last_processed = now

                self._process_frame(frame, tracker)
                if now - self._last_index_at >= index_interval and not self._index_pending:
                    self._last_index_at = now
                    self._queue_index(frame, tracker)
                self._persist()
        except Exception as exc:  # noqa: BLE001 - the service must not die silently
            logger.exception("camera worker crashed: %s", exc)
            self._last_error = f"Camera worker error: {exc}"
            self._set_status("error")
            self._persist(force=True)
        finally:
            source.release()
            self._detections = []
            self._status = "offline"
            self._persist(force=True)

    def _process_frame(self, frame: np.ndarray, tracker: ObjectTracker) -> None:
        height, width = frame.shape[:2]
        ctx = FrameContext(
            source_type="live",
            frame_number=self._live_frame_number,
            timestamp_seconds=0.0,
            captured_at=utcnow(),
            recording_name="ESP32 Live",
            tracker=tracker,
            detector_enabled=bool(self._config.get("detector_enabled", True)),
        )
        result = self.analyzer.analyze(frame, ctx, persist=False)
        self._live_frame_number += 1
        detection_dicts = []
        for det in result.detections:
            x1, y1, x2, y2 = det.xyxy
            detection_dicts.append(
                {
                    "track_id": int(getattr(det, "track_id", 0) or 0),
                    "object_class": det.class_name,
                    "confidence": round(float(det.confidence), 3),
                    "bbox": [
                        round(x1 / max(1, width), 4),
                        round(y1 / max(1, height), 4),
                        round(x2 / max(1, width), 4),
                        round(y2 / max(1, height), 4),
                    ],
                }
            )
        self._detections = detection_dicts
        self._last_raw_frame = frame
        self._frame_width, self._frame_height = width, height
        self._last_frame_at = utcnow()
        self._frames_received += 1

        # Refresh the measured FPS with a light exponential average.
        if self._measured_fps <= 0:
            self._measured_fps = float(self._config.get("live_fps", 2.0))
        else:
            self._measured_fps = 0.85 * self._measured_fps + 0.15 * float(self._config.get("live_fps", 2.0))

        try:
            self._annotated.set(encode_jpeg(annotate(frame, result.detections), quality=74, max_width=1024))
            self._raw.set(encode_jpeg(frame, quality=72, max_width=1024))
        except Exception as exc:  # noqa: BLE001 - preview encoding is best-effort
            logger.debug("preview encode failed: %s", exc)

    def _queue_index(self, frame: np.ndarray, tracker: ObjectTracker) -> None:
        try:
            ctx = FrameContext(
                source_type="live",
                frame_number=self._live_frame_number,
                timestamp_seconds=0.0,
                captured_at=utcnow(),
                recording_name="ESP32 Live",
                tracker=None,  # tracker already ran for this frame on the capture thread
                detector_enabled=False,
            )
            # Reuse the exact boxes/track ids shown in the preview.
            from app.services.detection.yolo import Detection

            detections = []
            for item in self._detections:
                detections.append(
                    Detection(
                        xyxy=(
                            item["bbox"][0] * frame.shape[1],
                            item["bbox"][1] * frame.shape[0],
                            item["bbox"][2] * frame.shape[1],
                            item["bbox"][3] * frame.shape[0],
                        ),
                        confidence=item["confidence"],
                        class_name=item["object_class"],
                        class_id=0,
                        crop=frame[
                            int(item["bbox"][1] * frame.shape[0]) : int(item["bbox"][3] * frame.shape[0]),
                            int(item["bbox"][0] * frame.shape[1]) : int(item["bbox"][2] * frame.shape[1]),
                        ],
                        track_id=item["track_id"],
                    )
                )
            frame_copy = frame.copy()
            self._index_pending = True
            self._executor.submit(self._index_frame, frame_copy, ctx, detections)
        except Exception as exc:  # noqa: BLE001
            self._index_pending = False
            logger.warning("live index submit failed: %s", exc)

    def _index_frame(self, frame: np.ndarray, ctx: FrameContext, detections: list) -> None:
        try:
            result = self.analyzer.analyze(frame, ctx, persist=True, detections=detections)
            if result.indexed:
                self._frames_indexed += 1
                self._objects_detected += result.object_count
        except Exception as exc:  # noqa: BLE001
            logger.warning("live indexing failed: %s", exc)
        finally:
            self._index_pending = False
            self._persist(force=True)

    # --------------------------------------------------------------- status
    def _set_status(self, status: str) -> None:
        self._status = status

    def _persist(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist_at < 2.0:
            return
        self._last_persist_at = now
        try:
            db = SessionLocal()
            try:
                row = db.get(CameraConfig, 1)
                if row is None:
                    row = CameraConfig(id=1)
                    db.add(row)
                row.status = self._status
                row.last_error = self._last_error
                row.last_frame_at = self._last_frame_at
                row.frames_received = self._frames_received
                row.frames_indexed = self._frames_indexed
                row.objects_detected = self._objects_detected
                row.frame_width = self._frame_width
                row.frame_height = self._frame_height
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - status persistence is best-effort
            logger.debug("camera status persist failed: %s", exc)

    def _sleep(self, seconds: float) -> None:
        self._stop.wait(timeout=max(0.2, seconds))

    # ------------------------------------------------------------ accessors
    def preview_jpeg(self, overlay: bool = True) -> tuple[bytes | None, float]:
        return (self._annotated if overlay else self._raw).get()

    def detections(self) -> list[dict]:
        return list(self._detections)

    def capture_snapshot(self, overlay: bool = True) -> dict:
        frame = self._last_raw_frame
        if frame is None:
            return {"ok": False, "detail": "No live frame available yet"}
        if overlay:
            from app.services.detection.yolo import Detection

            boxes = [
                Detection(
                    xyxy=(
                        d["bbox"][0] * frame.shape[1],
                        d["bbox"][1] * frame.shape[0],
                        d["bbox"][2] * frame.shape[1],
                        d["bbox"][3] * frame.shape[0],
                    ),
                    confidence=d["confidence"],
                    class_name=d["object_class"],
                    track_id=d["track_id"],
                )
                for d in self._detections
            ]
            image = annotate(frame, boxes)
        else:
            image = frame
        name, data = save_snapshot(image)
        return {
            "ok": True,
            "filename": name,
            "url": f"/api/media/snapshot/{name}",
            "captured_at": to_iso(utcnow()),
            "bytes": len(data),
        }

    def stats(self) -> dict:
        return {
            "running": self.running,
            "status": self._status,
            "last_error": self._last_error,
            "source_url": self._config.get("stream_url", ""),
            "source_kind": self._source_kind if self.running else "none",
            "source_label": self._source_label,
            "configured_fps": self._config.get("live_fps", 0),
            "measured_fps": round(self._measured_fps, 2),
            "index_interval_seconds": self._config.get("index_interval_seconds", 0),
            "detector_enabled": self._config.get("detector_enabled", True),
            "frame_width": self._frame_width,
            "frame_height": self._frame_height,
            "frames_received": self._frames_received,
            "frames_indexed": self._frames_indexed,
            "objects_detected": self._objects_detected,
            "last_frame_at": to_iso(self._last_frame_at),
            "index_pending": self._index_pending,
        }
