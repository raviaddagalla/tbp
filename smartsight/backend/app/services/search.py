"""Natural-language semantic search over indexed frames and objects.

CLIP maps the query text into the same space as the stored image embeddings.
Scene (whole-frame) and object (cropped detection) results are always kept
separate by collection, then merged and de-duplicated for display.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.base import SessionLocal
from app.db.models import Detection, Frame
from app.services.embedding.base import Embedder
from app.services.vectorstore import get_object_store, get_scene_store
from app.utils import as_utc, to_iso

logger = logging.getLogger(__name__)

SCENE_DEDUPE_SECONDS = 4.0
OBJECT_DEDUPE_SECONDS = 5.0


def _scene_key(hit) -> tuple:
    meta = hit.metadata
    return (meta.get("source_type"), int(meta.get("recording_id", 0) or 0))


def _object_key(hit) -> tuple:
    meta = hit.metadata
    track = int(meta.get("track_id", 0) or 0)
    # Without a track id every frame is its own candidate.
    identity = track if track else int(meta.get("frame_id", 0) or 0)
    return (meta.get("source_type"), int(meta.get("recording_id", 0) or 0), identity)


def _timeline(hit) -> float:
    """Position on the footage timeline used for de-duplication.

    Uploaded frames are processed seconds apart even when they are 0.5s apart
    in the video, so wall-clock ``ts_epoch`` would treat every sampled frame as
    unique. Use the video position for uploads and capture time for live frames.
    """
    meta = hit.metadata
    if str(meta.get("source_type", "")) == "upload":
        return float(meta.get("timestamp_seconds", 0) or 0)
    return float(meta.get("ts_epoch", 0) or 0)


def _dedupe(hits, key_fn, window_seconds: float):
    """Collapse near-identical frames into one result per N-second window.

    Windows are aligned to a fixed grid, so each identity/source contributes at
    most one hit per window and two results are never closer than the window
    (except across a boundary). A person present for a minute still yields a
    result every `window_seconds` instead of repeating every sampled frame.
    """
    windows: dict[tuple, dict[int, object]] = {}
    for hit in hits:
        slot = int(_timeline(hit) // window_seconds)
        bucket = windows.setdefault(key_fn(hit), {})
        current = bucket.get(slot)
        if current is None or hit.score > current.score:
            bucket[slot] = hit
    return sorted(
        (hit for bucket in windows.values() for hit in bucket.values()),
        key=lambda h: h.score,
        reverse=True,
    )


def _filters(source_type: str | None, recording_id: int | None, start: datetime | None, end: datetime | None) -> dict:
    filters: dict = {}
    if source_type:
        filters["source_type"] = source_type
    if recording_id:
        filters["recording_id"] = int(recording_id)
    if start or end:
        window: dict = {}
        if start:
            window["$gte"] = start.astimezone(timezone.utc).timestamp()
        if end:
            window["$lte"] = end.astimezone(timezone.utc).timestamp()
        filters["ts_epoch"] = window
    return filters


def _frame_details(frame_ids: list[int]) -> dict[int, dict]:
    if not frame_ids:
        return {}
    db = SessionLocal()
    try:
        frames = db.query(Frame).filter(Frame.id.in_(frame_ids)).all()
        detections = db.query(Detection).filter(Detection.frame_id.in_(frame_ids)).all()
        grouped: dict[int, list[dict]] = {}
        for det in detections:
            grouped.setdefault(det.frame_id, []).append(
                {
                    "object_class": det.object_class,
                    "track_id": det.track_id,
                    "confidence": round(det.confidence, 3),
                    "bbox": [det.x1, det.y1, det.x2, det.y2],
                    "thumbnail": det.thumbnail,
                    "colour": det.attributes,
                    "timestamp_seconds": det.timestamp_seconds,
                }
            )
        out = {}
        for frame in frames:
            out[frame.id] = {
                "frame_id": frame.id,
                "recording_id": frame.recording_id,
                "source_type": frame.source_type,
                "frame_number": frame.frame_number,
                "timestamp_seconds": frame.timestamp_seconds,
                "captured_at": to_iso(frame.captured_at),
                "thumbnail": frame.thumbnail,
                "width": frame.width,
                "height": frame.height,
                "detections": grouped.get(frame.id, []),
            }
        return out
    finally:
        db.close()


def _hit_payload(hit, match_type: str, details: dict[int, dict]) -> dict:
    meta = hit.metadata
    source_type = str(meta.get("source_type", "upload"))
    recording_id = int(meta.get("recording_id", 0) or 0)
    frame_id = int(meta.get("frame_id", 0) or 0)
    detail = details.get(frame_id, {})
    timestamp_seconds = float(meta.get("timestamp_seconds", 0) or 0)
    captured_at = meta.get("captured_at", "")
    playback_url = f"/api/recordings/{recording_id}/playback" if source_type == "upload" and recording_id else ""
    recording_name = str(meta.get("recording_name", "") or "")
    bbox = meta.get("bbox", "")
    return {
        "id": hit.id,
        "match_type": match_type,
        "score": round(float(hit.score), 4),
        "source_type": source_type,
        "recording_id": recording_id or None,
        "recording_name": recording_name,
        "source_label": recording_name if source_type == "upload" else "ESP32 Live camera",
        "frame_id": frame_id,
        "frame_number": int(meta.get("frame_number", 0) or 0),
        "timestamp_seconds": round(timestamp_seconds, 2),
        "captured_at": captured_at,
        "thumbnail_url": f"/api/media/thumb/{meta.get('thumbnail', '')}",
        "frame_thumbnail_url": f"/api/media/thumb/{meta.get('frame_thumbnail', meta.get('thumbnail', ''))}",
        "object_class": meta.get("object_class", ""),
        "track_id": int(meta.get("track_id", 0) or 0),
        "confidence": round(float(meta.get("confidence", 0) or 0), 3),
        "bbox": [float(v) for v in str(bbox).split(",")] if bbox and "," in str(bbox) else [],
        "playback_url": playback_url,
        "detections": detail.get("detections", []),
    }


def semantic_search(
    embedder: Embedder,
    query: str,
    *,
    mode: str = "both",
    limit: int = 12,
    source_type: str | None = None,
    recording_id: int | None = None,
    object_class: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    min_score: float = 0.0,
) -> dict:
    embedding = embedder.embed_text(query)
    base_filters = _filters(source_type, recording_id, start, end)
    scene_hits = []
    object_hits = []

    try:
        if mode in ("scene", "both"):
            # Fetch a deep candidate pool: de-duplication removes neighbouring
            # frames, so a shallow pool would leave only a couple of results.
            scene_hits = get_scene_store().query(embedding, top_k=max(limit * 6, 60), filters=base_filters)
    except Exception as exc:  # noqa: BLE001 - a store failure must not 500 the search
        logger.warning("scene search failed: %s", exc)
    try:
        if mode in ("object", "both"):
            object_filters = dict(base_filters)
            if object_class:
                object_filters["object_class"] = object_class
            object_hits = get_object_store().query(embedding, top_k=max(limit * 6, 60), filters=object_filters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("object search failed: %s", exc)

    scene_hits = [h for h in scene_hits if h.score >= min_score]
    object_hits = [h for h in object_hits if h.score >= min_score]

    scene_hits = _dedupe(scene_hits, _scene_key, SCENE_DEDUPE_SECONDS)
    object_hits = _dedupe(object_hits, _object_key, OBJECT_DEDUPE_SECONDS)

    selected: list[tuple[str, object]] = []
    if mode == "scene":
        selected = [("scene", hit) for hit in scene_hits[:limit]]
    elif mode == "object":
        selected = [("object", hit) for hit in object_hits[:limit]]
    else:
        # Balanced mix: half scene, half object, so neither collection can
        # crowd the other out purely because its scores run higher.
        half = max(1, limit // 2)
        merged = [("scene", hit) for hit in scene_hits[:half]] + [("object", hit) for hit in object_hits[:half]]
        merged.sort(key=lambda item: item[1].score, reverse=True)
        seen_frames: set[int] = set()
        for match_type, hit in merged:
            frame_id = int(hit.metadata.get("frame_id", 0))
            if frame_id and frame_id in seen_frames:
                continue
            selected.append((match_type, hit))
            if frame_id:
                seen_frames.add(frame_id)
        # Fill any shortfall from the remaining candidates.
        remaining = [("scene", hit) for hit in scene_hits[half:]] + [("object", hit) for hit in object_hits[half:]]
        remaining.sort(key=lambda item: item[1].score, reverse=True)
        for match_type, hit in remaining:
            if len(selected) >= limit:
                break
            frame_id = int(hit.metadata.get("frame_id", 0))
            if frame_id and frame_id in seen_frames:
                continue
            selected.append((match_type, hit))
            if frame_id:
                seen_frames.add(frame_id)
        selected = selected[:limit]

    frame_ids = [int(hit.metadata.get("frame_id", 0)) for _, hit in selected if hit.metadata.get("frame_id")]
    details = _frame_details(frame_ids)
    hits = [_hit_payload(hit, match_type, details) for match_type, hit in selected]

    return {
        "query": query,
        "mode": mode,
        "total": len(hits),
        "min_score": min_score,
        "hits": hits,
    }


def frame_detail(frame_id: int) -> dict | None:
    detail = _frame_details([frame_id]).get(frame_id)
    if detail is None:
        return None
    db = SessionLocal()
    try:
        frame = db.get(Frame, frame_id)
        if frame is None:
            return None
        detail["scene_vector_id"] = frame.scene_vector_id
        detail["thumbnail_url"] = f"/api/media/thumb/{frame.thumbnail}"
        detail["objects_count"] = frame.objects_count
        return detail
    finally:
        db.close()


def counts() -> dict:
    scene_store = get_scene_store()
    object_store = get_object_store()
    return {
        "scenes": scene_store.count(),
        "objects": object_store.count(),
    }


def timeline_bounds() -> dict:
    """Earliest/latest captured_at across indexed frames, for filter defaults."""
    db = SessionLocal()
    try:
        from sqlalchemy import func

        earliest = db.query(func.min(Frame.captured_at)).scalar()
        latest = db.query(func.max(Frame.captured_at)).scalar()
        return {"earliest": to_iso(as_utc(earliest)), "latest": to_iso(as_utc(latest))}
    finally:
        db.close()
