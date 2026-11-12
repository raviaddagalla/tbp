"""ByteTrack object tracking (single camera, no cross-camera identity)."""
from __future__ import annotations

import logging

import numpy as np

from app.services.detection.yolo import Detection

logger = logging.getLogger(__name__)


class ObjectTracker:
    """Thin, durable wrapper around supervision's ByteTrack.

    Track IDs are stable while an object stays visible. IDs are local to one
    recording or one live session — SmartSight does no re-identification.
    """

    def __init__(self, frame_rate: int = 2):
        self._frame_rate = max(1, int(round(frame_rate)))
        self._tracker = None
        self._warned = False

    def _ensure(self):
        if self._tracker is not None:
            return self._tracker
        import supervision as sv

        self._tracker = sv.ByteTrack(frame_rate=self._frame_rate)
        return self._tracker

    def update(self, detections: list[Detection]) -> list[int]:
        """Assign tracker ids in place (detection.track_id) and return them."""
        if not detections:
            return []
        try:
            import supervision as sv

            tracker = self._ensure()
            xyxy = np.asarray([d.xyxy for d in detections], dtype=np.float32)
            confidence = np.asarray([d.confidence for d in detections], dtype=np.float32)
            class_id = np.asarray([d.class_id for d in detections], dtype=np.int64)
            tracked = tracker.update_with_detections(
                sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
            )
            ids: list[int] = []
            raw = tracked.tracker_id.tolist() if tracked.tracker_id is not None else []
            for value in raw:
                ids.append(int(value) if value is not None else 0)
            # supervision may return fewer rows than inputs when it filters
            # low-score boxes; pad so indexes stay aligned with detections.
            if len(ids) < len(detections):
                ids.extend([0] * (len(detections) - len(ids)))
            for det, track_id in zip(detections, ids):
                det.track_id = track_id
            return ids
        except Exception as exc:  # noqa: BLE001 - tracking is an enhancement
            if not self._warned:
                logger.warning("ByteTrack unavailable (%s); using track id 0", exc)
                self._warned = True
            return [0] * len(detections)
