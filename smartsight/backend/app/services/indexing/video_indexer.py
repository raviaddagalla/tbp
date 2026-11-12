"""Background video indexing.

One worker thread consumes a queue so a large upload never blocks the API or
freezes the UI. Frames are read sequentially and only sampled ones are run
through detection/CLIP, so memory stays flat regardless of file length.

Progress is written to SQLite (`Recording.frames_indexed`) and surfaced by the
recordings API while the user watches the progress bar.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import timedelta
from pathlib import Path

import cv2

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Recording
from app.services.activity import record as record_activity
from app.services.analysis import FrameAnalyzer, FrameContext
from app.services.detection.tracker import ObjectTracker
from app.services.indexing.recordings import probe_video, purge_recording_data
from app.utils import as_utc, utcnow

logger = logging.getLogger(__name__)


class VideoIndexer:
    def __init__(self, analyzer: FrameAnalyzer):
        self.analyzer = analyzer
        self._queue: queue.Queue[int] = queue.Queue()
        self._pending: set[int] = set()
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: int | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="video-indexer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(-1)
        except queue.Full:  # pragma: no cover
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def recover_pending(self) -> None:
        """Re-queue work that was interrupted by a restart."""
        db = SessionLocal()
        try:
            rows = db.query(Recording).filter(Recording.status.in_(("queued", "processing"))).all()
            ids = [row.id for row in rows]
            for row in rows:
                row.status = "queued"
                row.frames_indexed = 0
                row.objects_detected = 0
            db.commit()
        finally:
            db.close()
        for recording_id in ids:
            self.enqueue(recording_id)
        if ids:
            logger.info("Re-queued %d interrupted recording(s)", len(ids))

    # ---------------------------------------------------------------- submit
    def enqueue(self, recording_id: int) -> bool:
        with self._lock:
            if recording_id in self._pending or recording_id == self._active:
                return False
            self._pending.add(recording_id)
            self._cancelled.discard(recording_id)
        self._queue.put(recording_id)
        return True

    def cancel(self, recording_id: int) -> None:
        with self._lock:
            self._cancelled.add(recording_id)
            self._pending.discard(recording_id)

    def state(self) -> dict:
        with self._lock:
            return {"active": self._active, "queued": sorted(self._pending)}

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                recording_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if recording_id == -1:
                break
            with self._lock:
                if recording_id in self._cancelled:
                    self._cancelled.discard(recording_id)
                    self._pending.discard(recording_id)
                    continue
                self._active = recording_id
                self._pending.discard(recording_id)
            try:
                self._process(recording_id)
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the worker
                logger.exception("indexing failed for recording %s: %s", recording_id, exc)
                self._fail(recording_id, f"Indexing failed: {exc}")
            finally:
                with self._lock:
                    self._active = None
                    self._cancelled.discard(recording_id)

    # --------------------------------------------------------------- process
    def _process(self, recording_id: int) -> None:
        settings = get_settings()
        db = SessionLocal()
        try:
            recording = db.get(Recording, recording_id)
            if recording is None:
                return
            path = Path(recording.path)
            info = probe_video(path) if path.is_file() else None
            if info is None or not info.ok:
                recording.status = "failed"
                recording.error = (info.error if info else "Recording file is missing from disk")
                db.commit()
                record_activity("recording", f"'{recording.name}' could not be indexed: {recording.error}", recording_id)
                return

            fps = info.fps if info.fps and info.fps > 0 else 25.0
            sample_fps = max(0.1, float(recording.sample_fps or settings.sample_fps_default))
            planned = int(info.duration_seconds * sample_fps) + 1 if info.duration_seconds else info.total_frames
            if settings.video_index_max_frames > 0:
                planned = min(planned, settings.video_index_max_frames)
            recording.status = "processing"
            recording.error = ""
            recording.duration_seconds = info.duration_seconds
            recording.fps = info.fps
            recording.width = info.width
            recording.height = info.height
            recording.total_frames = info.total_frames
            recording.frames_planned = max(0, planned)
            recording.frames_indexed = 0
            recording.objects_detected = 0
            db.commit()
            started_at = recording.created_at
            name = recording.name
        finally:
            db.close()

        record_activity("recording", f"Indexing started for '{name}' ({planned} frames planned)", recording_id)

        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self._fail(recording_id, "Could not open the video file for indexing")
            return
        tracker = ObjectTracker(frame_rate=max(1, int(round(sample_fps))))
        step = 1.0 / sample_fps
        next_sample = 0.0
        frame_index = 0
        sampled = 0
        objects = 0
        thumbnail = ""
        last_progress = time.monotonic()
        capped = False
        cancelled = False

        try:
            while not self._stop.is_set():
                if self._is_cancelled(recording_id):
                    cancelled = True
                    break
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                timestamp = frame_index / fps
                frame_index += 1
                if timestamp + (0.5 / fps) < next_sample:
                    continue
                next_sample += step

                if settings.video_index_max_frames and sampled >= settings.video_index_max_frames:
                    capped = True
                    break

                captured_at = as_utc(started_at) + timedelta(seconds=timestamp) if started_at else utcnow()
                ctx = FrameContext(
                    source_type="upload",
                    recording_id=recording_id,
                    recording_name=name,
                    frame_number=frame_index - 1,
                    timestamp_seconds=timestamp,
                    captured_at=captured_at,
                    tracker=tracker,
                    detector_enabled=True,
                )
                result = self.analyzer.analyze(frame, ctx, persist=True)
                if result.indexed:
                    sampled += 1
                    objects += result.object_count
                    if not thumbnail:
                        thumbnail = result.thumbnail

                now = time.monotonic()
                if now - last_progress >= 1.0:
                    last_progress = now
                    self._progress(recording_id, sampled, objects, thumbnail)
        finally:
            capture.release()

        if cancelled:
            self._cancel(recording_id)
            return

        self._finish(recording_id, sampled, objects, thumbnail, capped, info.duration_seconds)

    # --------------------------------------------------------------- helpers
    def _is_cancelled(self, recording_id: int) -> bool:
        with self._lock:
            return recording_id in self._cancelled

    def _progress(self, recording_id: int, sampled: int, objects: int, thumbnail: str) -> None:
        try:
            db = SessionLocal()
            try:
                recording = db.get(Recording, recording_id)
                if recording:
                    recording.frames_indexed = sampled
                    recording.objects_detected = objects
                    if thumbnail:
                        recording.thumbnail = thumbnail
                    db.commit()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - progress is best-effort
            logger.debug("progress write failed: %s", exc)

    def _finish(self, recording_id: int, sampled: int, objects: int, thumbnail: str, capped: bool, duration: float) -> None:
        db = SessionLocal()
        try:
            recording = db.get(Recording, recording_id)
            if recording is None:
                return
            name = recording.name
            if sampled == 0:
                recording.status = "failed"
                recording.error = "No frames could be decoded from this file"
                db.commit()
                record_activity("recording", f"'{name}' failed: no decodable frames", recording_id)
                return
            recording.status = "ready"
            recording.frames_indexed = sampled
            recording.objects_detected = objects
            recording.frames_planned = sampled
            if thumbnail:
                recording.thumbnail = thumbnail
            recording.completed_at = utcnow()
            if capped:
                recording.error = "Stopped at the configured indexing frame cap"
            db.commit()
            record_activity(
                "recording",
                f"'{name}' indexed: {sampled} frames, {objects} objects",
                recording_id,
            )
        finally:
            db.close()

    def _fail(self, recording_id: int, message: str) -> None:
        db = SessionLocal()
        try:
            recording = db.get(Recording, recording_id)
            if recording:
                recording.status = "failed"
                recording.error = message
                db.commit()
                record_activity("recording", f"'{recording.name}' failed: {message}", recording_id)
        finally:
            db.close()

    def _cancel(self, recording_id: int) -> None:
        db = SessionLocal()
        try:
            recording = db.get(Recording, recording_id)
            purge_recording_data(db, recording_id)
            if recording:
                recording.status = "cancelled"
                recording.frames_indexed = 0
                recording.objects_detected = 0
                recording.thumbnail = ""
                recording.completed_at = utcnow()
                db.commit()
                record_activity("recording", f"Indexing cancelled for '{recording.name}'", recording_id)
        finally:
            db.close()
