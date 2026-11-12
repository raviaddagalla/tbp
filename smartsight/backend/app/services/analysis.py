"""The shared computer-vision pipeline.

One code path serves both uploaded videos and the live ESP32-CAM:

    frame -> YOLO detect -> ByteTrack ids -> CLIP scene embedding
                                      \\-> crop CLIP embeddings
                                              -> SQLite (frames, detections)
                                              -> Chroma (scenes, objects)

`persist=False` runs detection/tracking only (used for live overlay frames that
are not sampled for indexing).
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.db.base import SessionLocal
from app.db.models import Detection as DetectionRow
from app.db.models import Frame
from app.media import normalized_bbox, save_thumbnail
from app.services.detection.attributes import dominant_color
from app.services.detection.tracker import ObjectTracker
from app.services.detection.yolo import Detection, get_detector
from app.services.embedding.base import Embedder
from app.services.vectorstore import get_object_store, get_scene_store
from app.utils import to_iso

logger = logging.getLogger(__name__)

# SQLite is single-writer; serialise the short metadata transactions.
_db_lock = threading.RLock()


@dataclass
class FrameContext:
    source_type: str  # "live" | "upload"
    frame_number: int
    timestamp_seconds: float
    captured_at: datetime
    recording_id: int | None = None
    recording_name: str = ""
    tracker: ObjectTracker | None = None
    detector_enabled: bool = True


@dataclass
class AnalysisResult:
    frame_id: int | None
    thumbnail: str
    detections: list[Detection] = field(default_factory=list)
    width: int = 0
    height: int = 0
    indexed: bool = False
    object_count: int = 0


class FrameAnalyzer:
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.scene_store = get_scene_store()
        self.object_store = get_object_store()

    # ------------------------------------------------------------------ core
    def analyze(
        self,
        frame_bgr: np.ndarray,
        ctx: FrameContext,
        persist: bool = True,
        detections: list[Detection] | None = None,
    ) -> AnalysisResult:
        """Run the pipeline on one frame.

        `detections` lets the live worker reuse the boxes/track ids it already
        computed for the annotated preview instead of detecting twice.
        """
        height, width = frame_bgr.shape[:2]
        if detections is None:
            detections = []
            if ctx.detector_enabled:
                detector = get_detector()
                if detector is not None:
                    detections = detector.detect(frame_bgr)
            if ctx.tracker is not None and detections:
                ctx.tracker.update(detections)

        if not persist:
            return AnalysisResult(None, "", detections, width, height, indexed=False)

        # Embed the scene and every crop in one batched CLIP call.
        embeddable = [d for d in detections if d.crop is not None and d.crop.size > 0]
        images = [frame_bgr] + [d.crop for d in embeddable]
        try:
            embeddings = self.embedder.embed_images_batch(images)
        except Exception as exc:  # noqa: BLE001 - one bad frame must not stop indexing
            logger.warning("embedding failed for frame %s: %s", ctx.frame_number, exc)
            return AnalysisResult(None, "", detections, width, height, indexed=False)

        scene_embedding = embeddings[0]
        crop_embeddings = embeddings[1:]
        frame_thumbnail = save_thumbnail(frame_bgr, prefix="frame")
        crop_thumbs = [save_thumbnail(det.crop, prefix="crop") for det in embeddable]
        object_vector_ids = [uuid.uuid4().hex for _ in embeddable]
        scene_vector_id = uuid.uuid4().hex
        captured_iso = to_iso(ctx.captured_at)
        recording_id = ctx.recording_id or 0

        rows_meta = []
        for det, crop_thumb, vector_id in zip(embeddable, crop_thumbs, object_vector_ids):
            x1, y1, x2, y2 = normalized_bbox(det.xyxy, width, height)
            rows_meta.append(
                {
                    "track_id": int(getattr(det, "track_id", 0) or 0),
                    "object_class": det.class_name,
                    "confidence": round(float(det.confidence), 4),
                    "bbox": (x1, y1, x2, y2),
                    "thumbnail": crop_thumb,
                    "vector_id": vector_id,
                    "xyxy": det.xyxy,
                }
            )

        frame_id = self._store_metadata(
            frame_thumbnail=frame_thumbnail,
            scene_vector_id=scene_vector_id,
            rows_meta=rows_meta,
            crop_embeddings=crop_embeddings,
            ctx=ctx,
            width=width,
            height=height,
        )

        try:
            self.scene_store.add(
                [scene_vector_id],
                [scene_embedding],
                [
                    {
                        "modality": "scene",
                        "source_type": ctx.source_type,
                        "recording_id": recording_id,
                        "recording_name": ctx.recording_name,
                        "frame_id": frame_id or 0,
                        "frame_number": ctx.frame_number,
                        "timestamp_seconds": round(float(ctx.timestamp_seconds), 3),
                        "captured_at": captured_iso,
                        "ts_epoch": ctx.captured_at.timestamp(),
                        "thumbnail": frame_thumbnail,
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("scene vector add failed: %s", exc)

        if rows_meta:
            try:
                self.object_store.add(
                    [row["vector_id"] for row in rows_meta],
                    crop_embeddings,
                    [
                        {
                            "modality": "object",
                            "source_type": ctx.source_type,
                            "recording_id": recording_id,
                            "recording_name": ctx.recording_name,
                            "frame_id": frame_id or 0,
                            "frame_number": ctx.frame_number,
                            "timestamp_seconds": round(float(ctx.timestamp_seconds), 3),
                            "captured_at": captured_iso,
                            "ts_epoch": ctx.captured_at.timestamp(),
                            "object_class": row["object_class"],
                            "track_id": row["track_id"],
                            "confidence": row["confidence"],
                            "bbox": ",".join(str(v) for v in row["bbox"]),
                            "thumbnail": row["thumbnail"],
                            "frame_thumbnail": frame_thumbnail,
                        }
                        for row in rows_meta
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("object vector add failed: %s", exc)

        return AnalysisResult(
            frame_id,
            frame_thumbnail,
            detections,
            width,
            height,
            indexed=True,
            object_count=len(rows_meta),
        )

    # -------------------------------------------------------------- metadata
    def _store_metadata(
        self,
        *,
        frame_thumbnail: str,
        scene_vector_id: str,
        rows_meta: list[dict],
        crop_embeddings: list[np.ndarray],
        ctx: FrameContext,
        width: int,
        height: int,
    ) -> int | None:
        colours: list[str] = []
        for embedding in crop_embeddings:
            colours.append(dominant_color(self.embedder, embedding) if embedding is not None else "")
        try:
            with _db_lock:
                db = SessionLocal()
                try:
                    frame = Frame(
                        source_type=ctx.source_type,
                        recording_id=ctx.recording_id,
                        frame_number=int(ctx.frame_number),
                        timestamp_seconds=round(float(ctx.timestamp_seconds), 3),
                        captured_at=ctx.captured_at,
                        thumbnail=frame_thumbnail,
                        scene_vector_id=scene_vector_id,
                        width=width,
                        height=height,
                        objects_count=len(rows_meta),
                    )
                    db.add(frame)
                    db.flush()
                    for row, colour in zip(rows_meta, colours):
                        x1, y1, x2, y2 = row["bbox"]
                        db.add(
                            DetectionRow(
                                frame_id=frame.id,
                                recording_id=ctx.recording_id,
                                source_type=ctx.source_type,
                                track_id=row["track_id"],
                                object_class=row["object_class"],
                                confidence=row["confidence"],
                                x1=x1,
                                y1=y1,
                                x2=x2,
                                y2=y2,
                                thumbnail=row["thumbnail"],
                                object_vector_id=row["vector_id"],
                                attributes=colour,
                                captured_at=ctx.captured_at,
                                timestamp_seconds=round(float(ctx.timestamp_seconds), 3),
                            )
                        )
                    db.commit()
                    return frame.id
                finally:
                    db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("frame metadata write failed: %s", exc)
            return None
