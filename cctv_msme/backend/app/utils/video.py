"""Shared small utilities."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


def encode_jpeg(bgr: np.ndarray, quality: int = 72, max_width: int | None = 640) -> bytes:
    img = bgr
    if max_width and img.shape[1] > max_width:
        scale = max_width / img.shape[1]
        img = cv2.resize(img, (max_width, int(img.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


_jpeg_lock = threading.Lock()


class LatestFrameBuffer:
    """Thread-safe holder for the latest JPEG per camera (MJPEG source)."""

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


OFFLINE_JPEG: bytes | None = None


def offline_placeholder_jpeg() -> bytes:
    global OFFLINE_JPEG
    if OFFLINE_JPEG is None:
        img = np.full((360, 640, 3), (23, 30, 45), dtype=np.uint8)
        cv2.putText(img, "CAMERA OFFLINE", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        OFFLINE_JPEG = encode_jpeg(img, quality=80, max_width=None)
    return OFFLINE_JPEG
