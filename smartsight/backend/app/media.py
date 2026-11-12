"""Media helpers: JPEG encoding, thumbnails, annotation, storage stats."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import cv2
import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_CLASS_COLORS = {
    "person": (99, 102, 241),
    "car": (16, 185, 129),
    "truck": (16, 185, 129),
    "bus": (16, 185, 129),
    "bicycle": (245, 158, 11),
    "motorcycle": (245, 158, 11),
    "dog": (236, 72, 153),
    "cat": (236, 72, 153),
    "backpack": (244, 63, 94),
    "handbag": (244, 63, 94),
    "suitcase": (244, 63, 94),
    "laptop": (14, 165, 233),
    "chair": (148, 163, 184),
}
_DEFAULT_COLOR = (168, 85, 247)


def encode_jpeg(image_bgr: np.ndarray, quality: int = 75, max_width: int | None = None) -> bytes:
    image = image_bgr
    if max_width and image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        image = cv2.resize(image, (max_width, int(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buffer.tobytes()


def save_thumbnail(image_bgr: np.ndarray, prefix: str = "frame") -> str:
    """Store a thumbnail and return its bare filename (served by /api/media/thumb)."""
    settings = get_settings()
    name = f"{prefix}_{uuid.uuid4().hex[:16]}.jpg"
    data = encode_jpeg(image_bgr, quality=72, max_width=settings.thumbnail_max_width)
    (settings.thumbs_dir / name).write_bytes(data)
    return name


def save_snapshot(image_bgr: np.ndarray) -> tuple[str, bytes]:
    settings = get_settings()
    name = f"snapshot_{uuid.uuid4().hex[:12]}.jpg"
    data = encode_jpeg(image_bgr, quality=88)
    (settings.snapshots_dir / name).write_bytes(data)
    return name, data


def normalized_bbox(xyxy: tuple[float, float, float, float], width: int, height: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = xyxy
    return (
        round(max(0.0, x1 / max(1, width)), 4),
        round(max(0.0, y1 / max(1, height)), 4),
        round(min(1.0, x2 / max(1, width)), 4),
        round(min(1.0, y2 / max(1, height)), 4),
    )


def annotate(frame_bgr: np.ndarray, detections: list, show_labels: bool = True) -> np.ndarray:
    """Draw boxes, labels, confidence and track ids onto a copy of the frame."""
    canvas = frame_bgr.copy()
    height, width = canvas.shape[:2]
    thickness = max(2, int(round(min(width, height) / 320)))
    font_scale = max(0.42, min(0.7, width / 1400))
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.xyxy]
        color = _CLASS_COLORS.get(det.class_name, _DEFAULT_COLOR)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        if not show_labels:
            continue
        label = det.class_name
        if getattr(det, "track_id", 0):
            label += f" #{det.track_id}"
        label += f" {det.confidence * 100:.0f}%"
        (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        label_y = max(text_h + baseline + 4, y1)
        cv2.rectangle(canvas, (x1, label_y - text_h - baseline - 4), (x1 + text_w + 8, label_y), color, -1)
        cv2.putText(
            canvas,
            label,
            (x1 + 4, label_y - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return canvas


_offline_cache: dict[str, bytes] = {}


def offline_jpeg(message: str = "CAMERA OFFLINE") -> bytes:
    """Clear placeholder so an <img> shows a labelled offline state, not a fake feed."""
    if message in _offline_cache:
        return _offline_cache[message]
    canvas = np.full((540, 960, 3), (23, 30, 45), dtype=np.uint8)
    cv2.circle(canvas, (480, 230), 42, (70, 80, 110), 3)
    cv2.line(canvas, (455, 205), (505, 255), (70, 80, 110), 4)
    cv2.putText(canvas, message, (330, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (235, 240, 250), 2, cv2.LINE_AA)
    cv2.putText(
        canvas,
        "SmartSight · start monitoring or check Settings",
        (300, 360),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (150, 165, 190),
        1,
        cv2.LINE_AA,
    )
    data = encode_jpeg(canvas, quality=80)
    _offline_cache[message] = data
    return data


def directory_size(path: Path) -> tuple[int, int]:
    """(bytes, file_count) for a directory tree."""
    total = 0
    count = 0
    if not path.exists():
        return 0, 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
