"""Zero-shot safety anomaly detection using CLIP itself.

Compares each sampled frame embedding against text prompts describing
potential safety issues. Uses a 'normal scene' baseline so a forklift in
a loading dock doesn't false-positive as 'person without helmet'.

Privacy-conscious: this detects events/entities, never identity.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import numpy as np

from app.core.config import get_settings
from app.services.alerts.tracking import track_movement
from app.services.activity_feed import record as record_activity
from app.services.db_support import save_alert

logger = logging.getLogger(__name__)

PROMPTS = {
    "normal_scene": "a normal scene in a factory",
    "no_helmet": "a person working without a safety helmet",
    "smoke_fire": "fire or smoke in a factory",
    "restricted_zone": "a person standing inside a clearly marked restricted danger zone",
    "spill": "a liquid spill on the factory floor",
}


class AnomalyDetector:
    def __init__(self, embedder, event_hub, threshold: float | None = None):
        self.embedder = embedder
        self.event_hub = event_hub
        settings = get_settings()
        self.threshold = threshold if threshold is not None else settings.anomaly_threshold
        self.cooldown = settings.anomaly_cooldown_seconds
        self._prompt_embs: dict[str, np.ndarray] = {}
        self._last_alert: dict[int, float] = {}

    def _prompt_embeddings(self) -> dict[str, np.ndarray]:
        if not self._prompt_embs:
            texts = list(PROMPTS.values())
            embs = self.embedder.embed_texts(texts)
            self._prompt_embs = {key: embs[i] for i, key in enumerate(PROMPTS)}
        return self._prompt_embs

    def score_frame(self, frame_emb: np.ndarray) -> tuple[str | None, float]:
        """Return (alert_type, anomaly_score) or (None, best)."""
        prompts = self._prompt_embeddings()
        scores = {k: float(np.dot(frame_emb, v)) for k, v in prompts.items()}
        baseline = scores["normal_scene"]
        candidates = [
            (k, v - baseline) for k, v in scores.items() if k != "normal_scene"
        ]
        best_type, best = max(candidates, key=lambda kv: kv[1])
        if best >= self.threshold:
            return best_type, best
        return None, max(0.0, best)

    def __call__(self, camera, frame_bgr, ts: datetime, frame_emb, thumb_rel: str, segment_id, offset: float):
        now = time.time()
        if now - self._last_alert.get(camera.id, 0.0) < self.cooldown:
            return None
        alert_type, score = self.score_frame(frame_emb)
        if not alert_type:
            return None

        # Persist the frame embedding next to the thumbnail for cross-camera tracking
        emb_path = None
        try:
            from app.core.config import get_settings

            stem = thumb_rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            emb_path = get_settings().thumbs_dir / f"{stem}.npy"
            np.save(emb_path, frame_emb.astype(np.float32))
        except Exception:  # noqa: BLE001
            logger.warning("alert embedding save failed", exc_info=True)

        description = _describe(alert_type, camera, ts)
        try:
            alert = save_alert(
                camera_id=camera.id,
                camera_name=camera.name,
                zone=camera.zone,
                alert_type=alert_type,
                description=description,
                score=round(score, 3),
                timestamp=ts,
                thumbnail_path=thumb_rel,
                segment_id=segment_id or "",
                clip_offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("alert save failed: %s", exc)
            return None

        self._last_alert[camera.id] = now

        # Cross-camera movement trail (privacy-scoped, entity-level)
        try:
            if emb_path and emb_path.exists():
                trail = track_movement(
                    vector_store=_vector_store(),
                    frame_emb=np.load(emb_path),
                    source_camera_id=camera.id,
                    timestamp=ts,
                    min_score=score * 0.8,
                )
                alert.trail_json = {"steps": trail}
                _commit_alert(alert)
        except Exception as exc:  # noqa: BLE001
            logger.warning("trail computation failed: %s", exc)

        record_activity("alert", f"Safety alert '{alert_type}' at {camera.name} ({camera.zone})", camera.id)
        try:
            import asyncio

            loop = self.event_hub._lock._loop  # noqa: SLF001
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.event_hub.broadcast(
                        "alert",
                        {
                            "id": alert.id,
                            "camera_id": alert.camera_id,
                            "camera_name": alert.camera_name,
                            "zone": alert.zone,
                            "alert_type": alert.alert_type,
                            "score": alert.score,
                            "timestamp": alert.timestamp,
                        },
                    ),
                    loop,
                )
        except Exception:  # noqa: BLE001
            pass
        return alert


def _describe(alert_type: str, camera, ts: datetime) -> str:
    zone = camera.zone or "unknown zone"
    when = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    labels = {
        "no_helmet": "Possible worker without a safety helmet",
        "smoke_fire": "Possible fire or smoke detected",
        "restricted_zone": "Person detected near a restricted/danger zone",
        "spill": "Possible liquid spill on the floor",
    }
    return f"{labels.get(alert_type, alert_type)} at '{camera.name}' ({zone}) on {when}."


def _vector_store():
    from app.services.vectorstore.factory import get_vector_store

    return get_vector_store()


def _commit_alert(alert) -> None:
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        db.add(alert)
        db.commit()
    finally:
        db.close()
