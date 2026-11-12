"""YOLO object detector.

Lazily loads the ultralytics model and serialises inference with a lock
(ultralytics is not thread-safe). If the model cannot be loaded, callers get
`None` and ingestion continues without detections rather than failing.
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
    track_id: int = 0


class ObjectDetector:
    """Thread-safe YOLOv8 wrapper via ultralytics."""

    def __init__(self, model_name: str = "yolov8n", confidence_threshold: float = 0.35):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from ultralytics import YOLO

        with self._lock:
            if self._model is None:
                logger.info("Loading YOLO model '%s'", self.model_name)
                self._model = YOLO(self.model_name)
        return self._model

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        try:
            model = self._ensure_model()
            with self._lock:
                results = model.predict(
                    frame_bgr,
                    conf=self.confidence_threshold,
                    imgsz=640,  # bounded CPU cost regardless of source resolution
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
            classes = boxes.cls.cpu().numpy().astype(int)
            names = model.names
            height, width = frame_bgr.shape[:2]
            out: list[Detection] = []
            for i in range(len(xyxy)):
                x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(width, x2), min(height, y2)
                if x2 - x1 < 8 or y2 - y1 < 8:
                    continue
                out.append(
                    Detection(
                        xyxy=(x1, y1, x2, y2),
                        confidence=float(confs[i]),
                        class_name=str(names.get(int(classes[i]), "object")),
                        class_id=int(classes[i]),
                        crop=frame_bgr[int(y1) : int(y2), int(x1) : int(x2)],
                    )
                )
            return out
        except Exception as exc:  # noqa: BLE001 - detection must never kill ingestion
            logger.warning("detection failed: %s", exc)
            return []

    def warmup(self) -> None:
        self._ensure_model()


_detector: ObjectDetector | None = None
_detector_lock = threading.Lock()


def detector_status() -> dict:
    """Report readiness without forcing a model load."""
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "model": settings.detector_model.split("/")[-1].split("\\")[-1],
        "ready": _detector is not None,
        "confidence_threshold": settings.detector_confidence_threshold,
        "enabled": settings.detector_model.strip().lower() not in ("", "none", "disabled"),
    }


def get_detector() -> ObjectDetector | None:
    """Cached detector, or None when detection is unavailable/disabled."""
    global _detector
    if _detector is not None:
        return _detector
    with _detector_lock:
        if _detector is None:
            from app.core.config import get_settings

            settings = get_settings()
            if settings.detector_model.strip().lower() in ("", "none", "disabled"):
                logger.info("Object detection disabled")
                return None
            candidate = ObjectDetector(settings.detector_model, settings.detector_confidence_threshold)
            try:
                candidate.warmup()
            except Exception as exc:  # noqa: BLE001
                logger.warning("YOLO unavailable (%s); detection disabled", exc)
                return None
            _detector = candidate
            logger.info("YOLO ready (%s)", settings.detector_model)
    return _detector
