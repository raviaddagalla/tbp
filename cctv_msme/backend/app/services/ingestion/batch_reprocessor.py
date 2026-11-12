"""Phase 3: offline batch reprocessing of recorded footage.

The live pipeline embeds each sampled frame (one CLIP vector per frame).
For footage older than `BATCH_REPROCESS_AFTER_HOURS`, a second pass pools
those already-stored frame embeddings into overlapping temporal windows
(window = 16 frames, stride 8 — overlapping so events are never split at a
window boundary) and writes `modality=clip_event` rows.

The pooled vector is the L2-normalized mean of the window's frame
embeddings: the cheapest "temporal model" that stays in CLIP text space,
so text queries compare directly against it (coarse-to-fine: fast frame
search finds candidate segments, the temporal rows re-rank them).
Swapping in a heavier temporal model later only changes this one function.

Never runs in the live capture thread: it is triggered nightly by the
maintenance worker and on demand via POST /api/reprocess/{camera_id}.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

WINDOW_FRAMES = 16
WINDOW_STRIDE = 8


def _l2_norm(arr: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(arr)
    return (arr / n).astype(np.float32) if n else arr.astype(np.float32)


def _pool(embeddings: list) -> np.ndarray:
    if not embeddings:
        return np.zeros(0, dtype=np.float32)
    stacked = np.stack([np.asarray(e, dtype=np.float32) for e in embeddings])
    return _l2_norm(stacked.mean(axis=0))


def reprocess_camera(db, store, camera, settings, now: datetime | None = None) -> dict:
    """Pool recorded frame rows for one camera into clip_event rows.

    Only segments that have no clip_event rows yet are processed, so the
    job is idempotent across nightly runs. Returns a small stats dict.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - getattr(settings, "batch_reprocess_after_hours", 24) * 3600

    frames = store.get(
        filters={
            "modality": "video",
            "camera_id": camera.id,
            "ts_epoch": {"$lte": cutoff},
        }
    )
    frames.sort(key=lambda r: float(r.metadata.get("ts_epoch", 0)))
    by_segment: dict[str, list] = {}
    for row in frames:
        seg = row.metadata.get("segment_id") or f"c{camera.id}"
        by_segment.setdefault(seg, []).append(row)

    stats = {"segment_count": len(by_segment), "windows_added": 0, "embeddings_pooled": 0}
    for seg, rows in by_segment.items():
        if len(rows) < WINDOW_FRAMES:
            continue
        # idempotence: skip segments already reprocessed
        existing = store.get(
            filters={"modality": "clip_event", "camera_id": camera.id, "segment_id": seg},
            limit=1,
        )
        if existing:
            continue
        try:
            added = _pool_segment(store, camera, seg, rows)
            stats["windows_added"] += added
            stats["embeddings_pooled"] += added * WINDOW_FRAMES
        except Exception as exc:  # noqa: BLE001 - batch job must not die mid-segment
            logger.warning("[cam %s] segment %s reprocess failed: %s", camera.id, seg, exc)
    return stats


def _pool_segment(store, camera, segment_id: str, rows: list) -> int:
    added = 0
    for start in range(0, len(rows) - WINDOW_FRAMES + 1, WINDOW_STRIDE):
        window = rows[start : start + WINDOW_FRAMES]
        mid = window[len(window) // 2]
        mid_meta = mid.metadata
        embs = [r.embedding for r in window if r.embedding is not None]
        if len(embs) < 8:  # too many missing embeddings in the window
            continue
        pooled = _pool(embs)
        if pooled.size == 0:
            continue
        ts_epoch = float(mid_meta.get("ts_epoch", 0))
        ts_dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
        store.add(
            [str(uuid.uuid4())],
            [pooled],
            [
                {
                    "modality": "clip_event",
                    "camera_id": camera.id,
                    "camera_name": mid_meta.get("camera_name", camera.name),
                    "zone": mid_meta.get("zone", camera.zone),
                    "timestamp": ts_dt.isoformat(),
                    "ts_epoch": ts_epoch,
                    "window_start": float(window[0].metadata.get("ts_epoch", 0)),
                    "window_end": float(window[-1].metadata.get("ts_epoch", 0)),
                    "frame_count": len(window),
                    "segment_id": segment_id,
                    "thumbnail": mid_meta.get("thumbnail", ""),
                    "clip_offset": mid_meta.get("clip_offset", 0),
                    "file_source": bool(mid_meta.get("file_source", False)),
                    "window_key": f"{segment_id}:{int(window[0].metadata.get('ts_epoch', 0))}",
                }
            ],
        )
        added += 1
    return added


def run_batch_reprocess(settings) -> dict:
    """Nightly sweep: reprocess every camera with batch_reprocess_enabled."""
    from app.db.base import SessionLocal
    from app.db.models import Camera
    from app.services.vectorstore.factory import get_vector_store

    store = get_vector_store()
    db = SessionLocal()
    try:
        cameras = db.query(Camera).filter(Camera.batch_reprocess_enabled.is_(True)).all()
    finally:
        db.close()
    total = {"cameras": len(cameras), "segments": 0, "windows": 0}
    for cam in cameras:
        try:
            stats = reprocess_camera(db, store, cam, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cam %s] batch reprocess failed: %s", cam.id, exc)
            continue
        total["segments"] += stats["segment_count"]
        total["windows"] += stats["windows_added"]
        if stats["windows_added"]:
            logger.info("[cam %s] batch reprocess: +%d clip_event windows", cam.id, stats["windows_added"])
    return total
