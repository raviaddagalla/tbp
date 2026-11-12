"""Retrieval helpers shared by search and the unified assistant."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.utils.video import to_iso

logger = logging.getLogger(__name__)


def search_documents(
    vector_store,
    embedder,
    query: str,
    top_k: int = 6,
    document_id: int | None = None,
    zones: list[str] | None = None,
):
    emb = embedder.embed_text(query)
    filters = {"modality": "document"}
    if document_id:
        filters["document_id"] = document_id
    if zones:
        filters["zone"] = {"$in": zones}
    try:
        return vector_store.query(emb, top_k=top_k, filters=filters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("document search failed: %s", exc)
        return []


def search_video(
    vector_store,
    embedder,
    query: str,
    camera_ids: list[int] | None = None,
    zones: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    top_k: int = 24,
):
    """Query video frames; returns hits ranked by similarity (not yet deduped)."""
    emb = embedder.embed_text(query)
    filters: dict = {"modality": "video"}
    if camera_ids:
        filters["camera_id"] = {"$in": camera_ids}
    if zones:
        filters["zone"] = {"$in": zones}
    if start or end:
        ts_filter: dict = {}
        if start:
            ts_filter["$gte"] = start.astimezone(timezone.utc).timestamp()
        if end:
            ts_filter["$lte"] = end.astimezone(timezone.utc).timestamp()
        if ts_filter:
            filters["ts_epoch"] = ts_filter
    try:
        return vector_store.query(emb, top_k=top_k, filters=filters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("video search failed: %s", exc)
        return []


def search_entities(
    vector_store,
    embedder,
    query: str,
    camera_ids: list[int] | None = None,
    zones: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    object_class: str | None = None,
    top_k: int = 24,
):
    """Phase 1: search detected objects (person/vehicle/... crops)."""
    emb = embedder.embed_text(query)
    filters: dict = {"modality": "object"}
    if camera_ids:
        filters["camera_id"] = {"$in": camera_ids}
    if zones:
        filters["zone"] = {"$in": zones}
    if object_class:
        filters["object_class"] = object_class
    if start or end:
        ts_filter: dict = {}
        if start:
            ts_filter["$gte"] = start.astimezone(timezone.utc).timestamp()
        if end:
            ts_filter["$lte"] = end.astimezone(timezone.utc).timestamp()
        if ts_filter:
            filters["ts_epoch"] = ts_filter
    try:
        return vector_store.query(emb, top_k=top_k, filters=filters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("entity search failed: %s", exc)
        return []


def describe_hit(hit, query: str) -> str:
    """Short human explanation of why a result matched."""
    meta = hit.metadata
    parts = [f"Frame similarity {hit.score:.2f} to your query"]
    words = [w.lower() for w in query.split() if len(w) > 3]
    if words:
        zone = (meta.get("zone") or "").lower()
        cam = (meta.get("camera_name") or "").lower()
        matched = [w for w in words if w in zone or w in cam]
        if matched:
            parts.append(f"matches location terms ({', '.join(matched)})")
        else:
            parts.append("based on visual content")
    return " ".join(parts)


def build_video_evidence(hits, limit: int = 6) -> list[dict]:
    """Convert raw video hits into chat-friendly evidence dicts."""
    out = []
    for h in hits[:limit]:
        meta = h.metadata
        out.append(
            {
                "camera_name": meta.get("camera_name", ""),
                "zone": meta.get("zone", ""),
                "timestamp": meta.get("timestamp", ""),
                "score": round(h.score, 3),
                "thumbnail_url": f"/api/streams/thumb/{meta.get('thumbnail', '')}",
                "clip_url": _clip_url(meta),
                "clip_offset_seconds": float(meta.get("clip_offset", 0) or 0),
                "description": describe_hit(h, meta.get("camera_name", "")),
            }
        )
    return out


def _clip_url(meta: dict) -> str:
    segment_id = meta.get("segment_id", "")
    camera_id = meta.get("camera_id", "")
    if meta.get("file_source") and camera_id:
        return f"/api/streams/file/{camera_id}"
    if segment_id and camera_id:
        return f"/api/streams/clip/{camera_id}/{segment_id}.mp4"
    return ""


def to_meta(hit) -> dict:
    return hit.metadata
