"""Natural-language video search + document search."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, require_roles, require_zone_scope
from app.db.models import User
from app.schemas import (
    DocumentSearchHit,
    EntitySearchHit,
    EntitySearchRequest,
    EntitySearchResponse,
    TemporalSearchHit,
    TemporalSearchResponse,
    VideoSearchHit,
    VideoSearchRequest,
    VideoSearchResponse,
)
from app.services.analytics.service import log_search
from app.services.rag.retriever import describe_hit, search_documents, search_entities, search_video
from app.state import state

router = APIRouter(prefix="/search", tags=["search"])

logger = logging.getLogger(__name__)


def _cluster_hits(raw: list, window_seconds: float = 10.0, key: str | None = None):
    """Pick the best-scoring hit per temporal cluster.

    Consecutive hits whose timestamps are within `window_seconds` of each
    other are treated as ONE occurrence of the thing (e.g. the camera panned
    across the swimming pool for 8 seconds -> one result, not 40). Hits
    separated by more than the window are different occurrences and are all
    returned — so a pool shown five times in the same video yields five
    results. `key` (optional) scopes clustering, e.g. per tracklet.
    Returns cluster representatives sorted by best score, descending.
    """
    clusters: list[dict] = []
    bucket: dict[str, int] = {}
    for hit in sorted(raw, key=lambda r: (float(r.metadata.get("ts_epoch", 0)), r.score), reverse=False):
        k = key(hit) if key else "all"
        ts = float(hit.metadata.get("ts_epoch", 0))
        idx = bucket.get(k)
        if idx is None or ts - clusters[idx]["ts"] > window_seconds:
            bucket[k] = len(clusters)
            clusters.append({"ts": ts, "best": hit})
        else:
            clusters[idx]["ts"] = ts
            if hit.score > clusters[idx]["best"].score:
                clusters[idx]["best"] = hit
    return sorted((c["best"] for c in clusters), key=lambda r: r.score, reverse=True)


def _parse_iso(value) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc)


@router.post("/video", response_model=VideoSearchResponse)
def video_search(
    body: VideoSearchRequest,
    user: User = Depends(require_roles("supervisor", "admin")),
):
    zones = require_zone_scope(user, body.zones)
    raw = search_video(
        state.vector_store,
        state.embedder,
        body.query,
        camera_ids=body.camera_ids,
        zones=zones,
        start=_parse_iso(body.start),
        end=_parse_iso(body.end),
        top_k=body.top_k * 3,
    )

    # Each temporal cluster = one distinct occurrence of what was searched for.
    # A swimming pool shown five times in the same video -> five results.
    hits = _cluster_hits(raw)[: body.top_k]

    result_hits = []
    for hit in hits:
        meta = hit.metadata
        ts = meta.get("timestamp", "")
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts_dt = datetime.now(timezone.utc)
        camera_id = int(meta.get("camera_id", 0))
        segment_id = meta.get("segment_id", "")
        clip_url = ""
        if meta.get("file_source"):
            clip_url = f"/api/streams/file/{camera_id}"
        elif segment_id:
            clip_url = f"/api/streams/clip/{camera_id}/{segment_id}.mp4"
        result_hits.append(
            VideoSearchHit(
                id=hit.id,
                camera_id=camera_id,
                camera_name=meta.get("camera_name", "Camera"),
                zone=meta.get("zone", ""),
                timestamp=ts_dt,
                score=round(hit.score, 3),
                thumbnail_url=f"/api/streams/thumb/{meta.get('thumbnail', '')}",
                clip_url=clip_url,
                clip_offset_seconds=float(meta.get("clip_offset", 0) or 0),
                explanation=describe_hit(hit, body.query),
            )
        )

    search_id = log_search(
        user.id,
        user.username,
        body.query,
        "video",
        {"camera_ids": body.camera_ids, "zones": body.zones},
        len(result_hits),
    )
    return VideoSearchResponse(query=body.query, hits=result_hits, total=len(result_hits), search_id=search_id)


@router.post("/entities", response_model=EntitySearchResponse)
def entity_search(
    body: EntitySearchRequest,
    user: User = Depends(require_roles("supervisor", "admin")),
):
    """Phase 1: search detected objects (people/vehicles) by visual content."""
    zones = require_zone_scope(user, body.zones)
    raw = search_entities(
        state.vector_store,
        state.embedder,
        body.query,
        camera_ids=body.camera_ids,
        zones=zones,
        start=_parse_iso(body.start),
        end=_parse_iso(body.end),
        object_class=body.object_class,
        top_k=body.top_k * 3,
    )

    # One best crop per tracklet occurrence (same tracklet seen again later in
    # the footage -> separate result, not merged).
    hits = _cluster_hits(raw, key=lambda h: f"{h.metadata.get('tracklet_local_id', 0)}|{h.metadata.get('camera_id')}")[
        : body.top_k
    ]

    result_hits = []
    for hit in hits:
        meta = hit.metadata
        ts = meta.get("timestamp", "")
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts_dt = datetime.now(timezone.utc)
        camera_id = int(meta.get("camera_id", 0))
        segment_id = meta.get("segment_id", "")
        clip_url = ""
        if meta.get("file_source"):
            clip_url = f"/api/streams/file/{camera_id}"
        elif segment_id:
            clip_url = f"/api/streams/clip/{camera_id}/{segment_id}.mp4"
        result_hits.append(
            EntitySearchHit(
                id=hit.id,
                camera_id=camera_id,
                camera_name=meta.get("camera_name", "Camera"),
                zone=meta.get("zone", ""),
                timestamp=ts_dt,
                score=round(hit.score, 3),
                object_class=meta.get("object_class", "object"),
                bbox=meta.get("bbox", ""),
                detection_confidence=float(meta.get("detection_confidence", 0) or 0),
                tracklet_local_id=int(meta.get("tracklet_local_id", 0) or 0),
                thumbnail_url=f"/api/streams/thumb/{meta.get('thumbnail', '')}",
                frame_thumbnail_url=f"/api/streams/thumb/{meta.get('frame_thumbnail', '')}",
                clip_url=clip_url,
                clip_offset_seconds=float(meta.get("clip_offset", 0) or 0),
                attrs={
                    "color": meta.get("attr_color", ""),
                    "clothing": meta.get("attr_clothing", ""),
                    "ppe": meta.get("attr_ppe", ""),
                },
            )
        )

    search_id = log_search(
        user.id,
        user.username,
        body.query,
        "video",
        {"mode": "entities", "camera_ids": body.camera_ids, "zones": body.zones, "object_class": body.object_class},
        len(result_hits),
    )
    return EntitySearchResponse(
        query=body.query,
        object_class=body.object_class,
        hits=result_hits,
        total=len(result_hits),
        search_id=search_id,
    )


@router.post("/temporal", response_model=TemporalSearchResponse)
def temporal_search(
    body: VideoSearchRequest,
    user: User = Depends(require_roles("supervisor", "admin")),
):
    """Phase 3 coarse-to-fine search over reprocessed footage.

    Stage 1: fast frame-level search gathers candidate segments (~50).
    Stage 2: only those candidates are re-ranked against the temporal
    clip_event rows (16-frame windows), so the heavier representation is
    only ever evaluated on a small candidate set. Falls back to the
    frame-level hits when no temporal rows exist yet (not reprocessed).
    """
    zones = require_zone_scope(user, body.zones)
    start_dt = _parse_iso(body.start)
    end_dt = _parse_iso(body.end)

    stage1 = search_video(
        state.vector_store,
        state.embedder,
        body.query,
        camera_ids=body.camera_ids,
        zones=zones,
        start=start_dt,
        end=end_dt,
        top_k=50,
    )
    segs_by_cam: dict[int, set[str]] = {}
    for hit in stage1:
        cam = int(hit.metadata.get("camera_id", 0))
        seg = hit.metadata.get("segment_id") or f"c{cam}"
        segs_by_cam.setdefault(cam, set()).add(seg)

    temporal_used = False
    raw = []
    if segs_by_cam:
        filters: dict = {"modality": "clip_event"}
        cams = list(segs_by_cam) if not body.camera_ids else body.camera_ids
        filters["camera_id"] = {"$in": cams}
        filters["segment_id"] = {"$in": [s for camset in segs_by_cam.values() for s in camset]}
        if zones:
            filters["zone"] = {"$in": zones}
        if start_dt:
            filters["ts_epoch"] = {"$gte": start_dt.timestamp()}
        if end_dt:
            filters["ts_epoch"] = {"$lte": end_dt.timestamp()}
        try:
            query_emb = state.embedder.embed_text(body.query)
            raw = state.vector_store.query(query_emb, top_k=body.top_k * 3, filters=filters)
        except Exception as exc:  # noqa: BLE001
            logger.warning("temporal search failed: %s", exc)
        temporal_used = bool(raw)

    if not raw:
        raw = stage1[: body.top_k]
    raw = sorted(raw, key=lambda r: r.score, reverse=True)[: body.top_k]

    hits = []
    for hit in raw:
        meta = hit.metadata
        ts = meta.get("timestamp", "")
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ts_dt = datetime.now(timezone.utc)
        camera_id = int(meta.get("camera_id", 0))
        segment_id = meta.get("segment_id", "")
        clip_url = ""
        if meta.get("file_source"):
            clip_url = f"/api/streams/file/{camera_id}"
        elif segment_id:
            clip_url = f"/api/streams/clip/{camera_id}/{segment_id}.mp4"
        hits.append(
            TemporalSearchHit(
                id=hit.id,
                camera_id=camera_id,
                camera_name=meta.get("camera_name", "Camera"),
                zone=meta.get("zone", ""),
                timestamp=ts_dt,
                score=round(hit.score, 3),
                thumbnail_url=f"/api/streams/thumb/{meta.get('thumbnail', '')}",
                clip_url=clip_url,
                clip_offset_seconds=float(meta.get("clip_offset", 0) or 0),
                explanation=describe_hit(hit, body.query),
                window_start=datetime.fromtimestamp(float(meta["window_start"]), tz=timezone.utc)
                if meta.get("window_start")
                else None,
                window_end=datetime.fromtimestamp(float(meta["window_end"]), tz=timezone.utc)
                if meta.get("window_end")
                else None,
                frame_count=int(meta.get("frame_count", 0)),
            )
        )

    search_id = log_search(
        user.id,
        user.username,
        body.query,
        "temporal",
        {"mode": "temporal", "camera_ids": body.camera_ids, "zones": body.zones},
        len(hits),
    )
    return TemporalSearchResponse(
        query=body.query,
        hits=hits,
        total=len(hits),
        temporal_used=temporal_used,
        search_id=search_id,
    )


@router.post("/documents", response_model=list[DocumentSearchHit])
def document_search(
    body: dict,
    user: User = Depends(get_current_user),
):
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    top_k = min(int(body.get("top_k", 10)), 30)
    zones = require_zone_scope(user, body.get("zones"))
    hits = search_documents(
        state.vector_store,
        state.embedder,
        query,
        top_k=top_k,
        zones=zones,
    )
    out = []
    for hit in hits:
        meta = hit.metadata
        out.append(
            DocumentSearchHit(
                id=hit.id,
                document_id=int(meta.get("document_id", 0)),
                filename=meta.get("filename", ""),
                page=int(meta.get("page", 0)),
                section=meta.get("section", ""),
                zone=meta.get("zone", ""),
                chunk_text=hit.text[:800],
                score=round(hit.score, 3),
            )
        )
    log_search(user.id, user.username, query, "doc", {}, len(out))
    return out
