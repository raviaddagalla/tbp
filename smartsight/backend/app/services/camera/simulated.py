"""Clearly labelled simulated camera source for hardware-free development.

It pans and zooms across a demo photograph, which produces real motion for the
tracker and real objects for YOLO — so the whole pipeline can be exercised
without an ESP32-CAM attached. Every frame is watermarked, and the API reports
`source_kind="simulated"`, so simulated footage is never mistaken for a real
camera.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 960, 540


class SimulatedSource:
    kind = "simulated"
    label = "Simulated demo scene (no hardware)"

    def __init__(self, url: str = "sim://demo"):
        self.url = url
        self._started = time.time()
        self._image: np.ndarray | None = None

    def _load(self) -> np.ndarray | None:
        if self._image is not None:
            return self._image
        path = Path(get_settings().demo_scene_path)
        if not path.is_file():
            logger.warning("demo scene missing: %s", path)
            return None
        image = cv2.imread(str(path))
        if image is None:
            return None
        # Work at a comfortable size; the demo photo is larger than the frame.
        self._image = image
        return image

    def open(self) -> bool:
        return self._load() is not None

    def read(self) -> tuple[bool, np.ndarray | None]:
        image = self._load()
        if image is None:
            return False, None
        elapsed = time.time() - self._started
        src_h, src_w = image.shape[:2]
        zoom = 1.0 + 0.10 * np.sin(elapsed * 0.22)
        crop_w = int(min(src_w, src_w / zoom))
        crop_h = int(min(src_h, crop_w * HEIGHT / WIDTH))
        if crop_h > src_h:
            crop_h = src_h
        max_x = max(0, src_w - crop_w)
        max_y = max(0, src_h - crop_h)
        x0 = int(max_x * (0.5 + 0.5 * np.sin(elapsed * 0.13)))
        y0 = int(max_y * (0.5 + 0.5 * np.sin(elapsed * 0.09 + 1.1)))
        crop = image[y0 : y0 + crop_h, x0 : x0 + crop_w]
        frame = cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
        cv2.rectangle(frame, (0, 0), (WIDTH - 1, HEIGHT - 1), (99, 102, 241), 2)
        cv2.putText(
            frame,
            "SIMULATED SOURCE",
            (14, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return True, frame

    def release(self) -> None:
        return None
