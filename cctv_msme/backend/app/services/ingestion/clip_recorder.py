"""Rolling video clip recorder.

Writes short H.264 MP4 segments (PyAV preferred — browser-playable; falls
back to OpenCV mp4v if PyAV is unavailable). A new segment file is started
every `segment_seconds`; old segments beyond the retention window are
deleted. Clip files give search results a playable link, not just a still.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClipRecorder:
    def __init__(
        self,
        camera_id: int,
        clips_dir: Path,
        segment_seconds: int = 30,
        target_fps: float = 1.0,
        retention_hours: int = 72,
    ):
        self.camera_id = camera_id
        self.clips_dir = clips_dir
        self.segment_seconds = max(10, segment_seconds)
        self.target_fps = target_fps
        self.retention = timedelta(hours=max(1, retention_hours))
        self.camera_dir = clips_dir / str(camera_id)
        self.camera_dir.mkdir(parents=True, exist_ok=True)

        self._writer = None
        self._seg_start: datetime | None = None
        self._segment_id: str | None = None
        self._last_write_ts = 0.0
        self._width = self._height = 0
        self._backend = "pyav"
        self._segments: dict[str, float] = {}  # segment_id -> start epoch (for offsets)

        if not self._try_import_pyav():
            self._backend = "opencv"
            logger.warning("PyAV unavailable; clips will use OpenCV mp4v (may not play in browsers).")

    @staticmethod
    def _try_import_pyav() -> bool:
        try:
            import av  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------- state
    @property
    def current_segment_id(self) -> str | None:
        return self._segment_id

    def segment_start(self, segment_id: str) -> float | None:
        return self._segments.get(segment_id)

    # ------------------------------------------------------------- write
    def write(self, frame_bgr: np.ndarray, ts: datetime | None = None) -> str | None:
        """Throttled to target_fps. Returns current segment_id or None."""
        now = time.time()
        if now - self._last_write_ts < 1.0 / max(0.2, self.target_fps):
            return self._segment_id
        self._last_write_ts = now
        ts = ts or _utcnow()

        if self._writer is None:
            self._open_segment(frame_bgr, ts)
        elif (ts - self._seg_start) >= timedelta(seconds=self.segment_seconds):
            self._close_segment()
            self._open_segment(frame_bgr, ts)

        if self._backend == "pyav":
            self._write_pyav(frame_bgr)
        else:
            self._write_opencv(frame_bgr)
        return self._segment_id

    # ------------------------------------------------------------- pyav
    def _write_pyav(self, frame_bgr: np.ndarray) -> None:
        import av

        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(frame_bgr), format="bgr24")
        frame.pts = None
        for packet in self._writer.encode(frame):
            self._container.mux(packet)

    # ---------------------------------------------------------- opencv
    def _write_opencv(self, frame_bgr: np.ndarray) -> None:
        import cv2

        self._writer.write(frame_bgr)

    # ---------------------------------------------------------- segments
    def _open_segment(self, frame_bgr: np.ndarray, ts: datetime) -> None:
        h, w = frame_bgr.shape[:2]
        self._width, self._height = w, h
        epoch = int(ts.timestamp())
        self._segment_id = f"{self.camera_id}_{epoch}"
        self._seg_start = ts
        self._segments[self._segment_id] = float(epoch)
        path = self.camera_dir / f"{self._segment_id}.mp4"

        if self._backend == "pyav":
            import av
            from fractions import Fraction

            self._container = av.open(str(path), mode="w", format="mp4")
            rate = Fraction(max(1, int(round(self.target_fps))), 1)
            stream = self._container.add_stream("h264", rate=rate)
            stream.width, stream.height = w, h
            stream.pix_fmt = "yuv420p"
            self._writer = stream
        else:
            import cv2

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(str(path), fourcc, max(0.2, self.target_fps), (w, h))

    def _close_segment(self) -> None:
        if self._writer is None:
            return
        seg_id = self._segment_id
        try:
            if self._backend == "pyav":
                for packet in self._writer.encode(None):
                    self._container.mux(packet)
                self._container.close()
            else:
                self._writer.release()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] clip finalize error: %s", self.camera_id, exc)
        self._writer = None
        self._seg_start = None
        # Mirror the finished segment to the shared bucket (best-effort).
        if seg_id:
            try:
                from app.services.media_storage import media_put_file

                media_put_file(f"clips/{self.camera_id}/{seg_id}.mp4", self.camera_dir / f"{seg_id}.mp4")
            except Exception:  # noqa: BLE001
                pass
        self._cleanup_old()

    def _cleanup_old(self) -> None:
        try:
            cutoff = _utcnow() - self.retention
            for f in self.camera_dir.glob("*.mp4"):
                try:
                    if f.stat().st_mtime < cutoff.timestamp():
                        f.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError as exc:  # noqa: BLE001
            logger.debug("cleanup skipped: %s", exc)

    def close(self) -> None:
        self._close_segment()
