"""YOLO object detector (Phase 1).

`ObjectDetector` lazily loads the ultralytics model on first use and guards
inference with a lock (ultralytics is not thread-safe). If the model cannot
be loaded (missing weights, missing package, no network for first download),
`get_detector()` falls back to a no-op detector so cameras keep indexing
frames — detection is an enhancement, never a single point of failure.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single detected object in a frame (pixel coordinates)."""

    xyxy: tuple[float, float, float, float]
    confidence: float
    class_name: str
    class_id: int = 0
    crop: np.ndarray = field(default_factory=lambda: np.zeros((0, 0, 3), dtype=np.uint8))


class ObjectDetector:
    """Thread-safe YOLO wrapper via ultralytics."""

    def __init__(self, model_name: str = "yolov8n", confidence_threshold: float = 0.35):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from ultralytics import YOLO  # local import: only needed when detecting

        with self._lock:
            if self._model is None:
                logger.info("Loading YOLO model '%s' (first inference may download weights)", self.model_name)
                self._model = YOLO(self.model_name)
        return self._model

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Run inference; returns [] on any failure."""
        try:
            model = self._ensure_model()
            with self._lock:
                results = model.predict(
                    frame_bgr,
                    conf=self.confidence_threshold,
                    imgsz=640,  # fixed inference size: full-frame CPU cost stays bounded
                    verbose=False,
                    device=None,
                )
            if not results:
                return []
            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                return []
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            names = model.names
            out: list[Detection] = []
            h, w = frame_bgr.shape[:2]
            for i in range(len(xyxy)):
                x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue  # degenerate box (mostly occluded)
                crop = frame_bgr[int(y1) : int(y2), int(x1) : int(x2)]
                out.append(
                    Detection(
                        xyxy=(x1, y1, x2, y2),
                        confidence=float(confs[i]),
                        class_name=str(names.get(int(cls[i]), "object")),
                        class_id=int(cls[i]),
                        crop=crop,
                    )
                )
            return out
        except Exception as exc:  # noqa: BLE001 - detection must never kill ingestion
            logger.warning("detection failed: %s", exc)
            return []


class NoopDetector:
    """Fallback when ultralytics/weights are unavailable."""

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        return []


_detector_singleton = None
_detector_lock = threading.Lock()


def get_detector() -> ObjectDetector | NoopDetector:
    """Cached detector; degrades to a no-op if the model cannot load."""
    global _detector_singleton
    if _detector_singleton is not None:
        return _detector_singleton
    with _detector_lock:
        if _detector_singleton is not None:
            return _detector_singleton
        from app.core.config import get_settings

        settings = get_settings()
        if settings.detector_model.strip().lower() in ("", "none", "disabled"):
            logger.info("Object detection disabled (DETECTOR_MODEL=%s)", settings.detector_model)
            _detector_singleton = NoopDetector()
            return _detector_singleton
        try:
            det = ObjectDetector(settings.detector_model, settings.detector_confidence_threshold)
            det._ensure_model()  # fail fast so we degrade now, not mid-ingestion
            _detector_singleton = det
            logger.info("Object detector ready (%s)", settings.detector_model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("YOLO unavailable (%s); object detection disabled", exc)
            _detector_singleton = NoopDetector()
        return _detector_singleton
