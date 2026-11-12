"""Cross-camera tracklet stitching (Phase 2).

Given an event on a source camera (an alert), find the same person on other
cameras by following the calibrated floor-plan graph (CameraAdjacency edges):
only graph-adjacent cameras within the expected transit-time window are
considered, and candidates are scored as

    confidence = parent_confidence * (α·reid_similarity + β·time_fit + γ·1.0) * decay

with α/β/γ from STITCH_WEIGHTS (default 1.0,1.0,1.0). Each hop multiplies
the confidence by HOP_DECAY, so long chains carry visibly lower confidence.

ReID embeddings live on the Tracklet row (separate from the CLIP object
vectors — never mix distance spaces), so no second vector collection is
needed: the adjacency + transit-window filter keeps the candidate set tiny.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone

import numpy as np

logger = logging.getLogger(__name__)

HOP_DECAY = 0.7  # confidence multiplier per graph hop
_BEAM = 3        # keep the top-K candidate chains per hop (work bound)
DEFAULT_WEIGHTS = (1.0, 1.0, 1.0)


def decode_b64_emb(blob: str) -> np.ndarray:
    if not blob:
        return np.zeros(0, dtype=np.float32)
    try:
        return np.frombuffer(base64.b64decode(blob), dtype=np.float32)
    except Exception:  # noqa: BLE001
        return np.zeros(0, dtype=np.float32)


def _naive_utc(dt: datetime) -> datetime:
    """Tracklet timestamps round-trip through SQLite as naive UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _reid_sim(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    return float(np.clip(float(np.dot(a, b)), 0.0, 1.0))


def _time_fit(transit_seconds: float, lo: int, hi: int) -> float:
    """1.0 at the window midpoint, linearly down to 0.0 at/outside the edges."""
    if lo <= 0:
        lo = 1
    if hi < lo:
        hi = lo
    mid = (lo + hi) / 2.0
    half = max(1e-6, (hi - lo) / 2.0)
    return float(np.clip(1.0 - abs(transit_seconds - mid) / half, 0.0, 1.0))


class _Node:
    __slots__ = ("tracklet_id", "local_track_id", "camera_id", "arrival_ts", "confidence", "reid", "hop")

    def __init__(self, tracklet_id, local_track_id, camera_id, arrival_ts, confidence, reid, hop):
        self.tracklet_id = tracklet_id
        self.local_track_id = local_track_id
        self.camera_id = camera_id
        self.arrival_ts = arrival_ts
        self.confidence = confidence
        self.reid = reid
        self.hop = hop


def stitch_trail(
    db,
    source_camera_id: int,
    ts: datetime,
    *,
    max_hops: int = 6,
    min_confidence: float = 0.15,
    weights: tuple[float, float, float] | None = None,
    vector_store=None,
) -> list[dict]:
    """Follow the source camera's person tracklet across adjacent cameras.

    Returns an ordered list of steps, each:
      {camera_id, camera_name, zone, timestamp, score, confidence, hop,
       tracklet_local_id, thumbnail, clip_url, clip_offset_seconds}
    `score` is kept equal to `confidence` so existing alert-trail rendering
    (which reads `score`) keeps working.
    """
    from app.db.models import Camera, CameraAdjacency, Tracklet

    w_reid, w_time, w_adj = weights or DEFAULT_WEIGHTS
    w_sum = max(1e-6, w_reid + w_time + w_adj)

    cams = {c.id: c for c in db.query(Camera).all()}
    if source_camera_id not in cams:
        return []

    naive = _naive_utc(ts)
    src = (
        db.query(Tracklet)
        .filter(
            Tracklet.camera_id == source_camera_id,
            Tracklet.object_class == "person",
            Tracklet.start_ts <= naive,
            Tracklet.end_ts >= naive,
        )
        .order_by(Tracklet.end_ts.desc())
        .first()
    )
    if src is None:
        src = (
            db.query(Tracklet)
            .filter(Tracklet.camera_id == source_camera_id, Tracklet.object_class == "person")
            .order_by(Tracklet.end_ts.desc())
            .first()
        )
    if src is None:
        return []

    def _thumb(camera_id: int, local_track_id: int) -> dict:
        out = {"thumbnail": "", "clip_url": "", "clip_offset_seconds": 0.0}
        if vector_store is None:
            return out
        try:
            rows = vector_store.get(
                filters={
                    "modality": "object",
                    "camera_id": camera_id,
                    "tracklet_local_id": local_track_id,
                },
                limit=1,
            )
        except Exception:  # noqa: BLE001 - thumbnails are cosmetic
            return out
        if rows:
            meta = rows[0].metadata
            out["thumbnail"] = f"/api/streams/thumb/{meta.get('frame_thumbnail') or meta.get('thumbnail', '')}"
            if meta.get("file_source"):
                out["clip_url"] = f"/api/streams/file/{camera_id}"
            elif meta.get("segment_id"):
                out["clip_url"] = f"/api/streams/clip/{camera_id}/{meta['segment_id']}.mp4"
            out["clip_offset_seconds"] = float(meta.get("clip_offset", 0) or 0)
        return out

    start_node = _Node(
        src.id, src.local_track_id, source_camera_id,
        _naive_utc(src.end_ts), 1.0, decode_b64_emb(src.reid_embedding), 0,
    )
    beam = [start_node]
    seen = {(source_camera_id, src.local_track_id)}
    steps: list[dict] = []

    for hop in range(1, max_hops + 1):
        next_beam: list[_Node] = []
        for node in beam:
            edges = (
                db.query(CameraAdjacency)
                .filter(CameraAdjacency.from_camera_id == node.camera_id)
                .all()
            )
            for edge in edges:
                to = edge.to_camera_id
                lo, hi = edge.expected_transit_seconds_min, edge.expected_transit_seconds_max
                start = node.arrival_ts + timedelta(seconds=max(0, lo))
                end = node.arrival_ts + timedelta(seconds=max(lo, hi))
                cands = (
                    db.query(Tracklet)
                    .filter(
                        Tracklet.camera_id == to,
                        Tracklet.object_class == "person",
                        Tracklet.end_ts >= start,
                        Tracklet.end_ts <= end,
                    )
                    .all()
                )
                for cand in cands:
                    key = (to, cand.local_track_id)
                    if key in seen:
                        continue
                    cand_reid = decode_b64_emb(cand.reid_embedding)
                    transit = (cand.end_ts - node.arrival_ts).total_seconds()
                    sim = _reid_sim(node.reid, cand_reid)
                    tfit = _time_fit(transit, lo, hi)
                    hop_score = (w_reid * sim + w_time * tfit + w_adj * 1.0) / w_sum
                    conf = node.confidence * hop_score * HOP_DECAY
                    if conf < min_confidence:
                        continue
                    seen.add(key)
                    cam = cams.get(to)
                    thumb = _thumb(to, cand.local_track_id)
                    ts_out = _naive_utc(cand.end_ts)
                    if ts_out.tzinfo is None:
                        ts_out = ts_out.replace(tzinfo=timezone.utc)
                    steps.append(
                        {
                            "camera_id": to,
                            "camera_name": cam.name if cam else f"Camera {to}",
                            "zone": cam.zone if cam else "",
                            "timestamp": ts_out.isoformat(),
                            "score": round(conf, 3),
                            "confidence": round(conf, 3),
                            "hop": hop,
                            "tracklet_local_id": cand.local_track_id,
                            "reid_similarity": round(sim, 3),
                            "transit_seconds": round(transit, 1),
                            **thumb,
                        }
                    )
                    next_beam.append(
                        _Node(cand.id, cand.local_track_id, to, cand.end_ts, conf, cand_reid, hop)
                    )
        if not next_beam:
            break
        next_beam.sort(key=lambda n: n.confidence, reverse=True)
        beam = next_beam[: _BEAM]

    steps.sort(key=lambda s: s["hop"])
    return steps
