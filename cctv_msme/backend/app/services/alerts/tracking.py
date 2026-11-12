"""Cross-camera entity movement tracking (privacy-conscious).

Phase 2: given an event on a source camera, follow the person's tracklet
across the calibrated floor-plan graph. Candidates come ONLY from
graph-adjacent cameras within their expected transit-time windows, scored
as α·reid_similarity + β·time_fit + γ·adjacency_confidence (STITCH_WEIGHTS)
with a confidence that decays per hop. This is NOT facial or biometric
recognition — it is tracklet matching with an honest confidence score.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def track_movement(
    vector_store,
    frame_emb,
    source_camera_id: int,
    timestamp,
    window_minutes: int = 10,
    min_score: float = 0.2,
    max_steps: int = 6,
) -> list[dict]:
    """Phase 2 tracklet stitching.

    `frame_emb`/`window_minutes` are retained for signature compatibility
    with the alert pipeline; the old whole-frame similarity search is gone.
    Without calibrated adjacency edges, no cross-camera trail is suggested
    (empty list) rather than guessing across unrelated zones.
    """
    from app.core.config import get_settings
    from app.db.base import SessionLocal
    from app.services.reid.stitching import stitch_trail

    db = SessionLocal()
    try:
        weights = tuple(get_settings().stitch_weight_list[:3])
        return stitch_trail(
            db,
            source_camera_id,
            timestamp,
            max_hops=max_steps,
            min_confidence=max(0.05, min_score),
            weights=weights,
            vector_store=vector_store,
        )
    finally:
        db.close()
