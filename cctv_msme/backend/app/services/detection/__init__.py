"""Object detection: YOLO detector with a no-op fallback so the ingestion
pipeline never dies when weights are missing or ultralytics is absent."""
from .yolo import Detection, ObjectDetector, get_detector  # noqa: F401
