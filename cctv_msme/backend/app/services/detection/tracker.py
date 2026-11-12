"""Per-camera object tracker (Phase 1).

Wraps supervision's ByteTrack and aggregates per-track object embeddings into
Tracklet rows (backend/app/db/models.py). A tracklet is the stable identity of
one object within one camera over time; cross-camera stitching of tracklets
happens in Phase 2 via ReID embeddings.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

TRACK_FINALIZE_SECONDS = 3.0   # a track is dead if unseen for this long
TRACK_PERSIST_INTERVAL = 15.0  # heartbeat for active tracks (DB churn bound)


def _b64(emb: np.ndarray) -> str:
    return base64.b64encode(np.asarray(emb, dtype=np.float32).tobytes()).decode("ascii")


def _mean_emb(emb_list: list[np.ndarray]) -> np.ndarray:
    if not emb_list:
        return np.zeros(0, dtype=np.float32)
    arr = np.stack(emb_list)
    mean = arr.mean(axis=0)
    n = np.linalg.norm(mean)
    return (mean / n).astype(np.float32) if n else mean


def _as_aware(dt: datetime) -> datetime:
    """SQLite round-trips naive UTC datetimes; normalize for comparisons."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class _TrackState:
    __slots__ = (
        "track_id", "object_class", "start_ts", "end_ts", "frame_count",
        "embs", "attrs", "reid_embs", "last_seen",
    )

    def __init__(self, track_id: int, object_class: str, ts: datetime, emb: np.ndarray, attrs: dict):
        self.track_id = track_id
        self.object_class = object_class
        self.start_ts = ts
        self.end_ts = ts
        self.frame_count = 1
        self.embs: list[np.ndarray] = [emb]
        self.attrs = dict(attrs)
        self.reid_embs: list[np.ndarray] = []
        self.last_seen = time.time()


class TrackletTracker:
    """Stateful per-camera tracker. Not thread-safe; call from one worker.

    update() -> (finalized_tracklets, active_count)
    """

    def __init__(self, camera_id: int, persist: bool = True, frame_rate: int = 5):
        self.camera_id = camera_id
        self.persist = persist
        self._tracker = None  # supervision ByteTrack, lazy
        self._frame_rate = frame_rate
        self._states: dict[int, _TrackState] = {}
        self._last_persist = 0.0
        self._lock = threading.Lock()

    def _ensure_tracker(self):
        if self._tracker is not None:
            return self._tracker
        import supervision as sv

        self._tracker = sv.ByteTrack(frame_rate=max(1, self._frame_rate))
        return self._tracker

    def update(
        self,
        detections: list,
        ts: datetime,
        emb_by_index: list[np.ndarray],
        attrs_by_index: list[dict],
        reid_by_index: list[np.ndarray] | None = None,
    ) -> tuple[int, int, list[int]]:
        """Feed per-detection data. `detections` must expose xyxy, confidence,
        class_name; embeddings/attrs parallel the detections list. Optional
        ReID embeddings (parallel, Phase 2) are aggregated per tracklet for
        cross-camera stitching.
        Returns (finalized_count, active_track_count, track_ids_by_index)."""
        if not detections:
            finalized = self._finalize_stale(ts)
            return finalized, len(self._states), []
        tracker = self._ensure_tracker()

        xyxy = np.asarray([d.xyxy for d in detections], dtype=np.float32)
        conf = np.asarray([d.confidence for d in detections], dtype=np.float32)
        cls = np.asarray([d.class_id for d in detections], dtype=np.int64)
        import supervision as sv

        tracked = tracker.update_with_detections(
            sv.Detections(xyxy=xyxy, confidence=conf, class_id=cls)
        )
        tids_by_index: list[int] = []
        if tracked.tracker_id is not None:
            tid_list = tracked.tracker_id.tolist()
            tids_by_index = [int(t) if t is not None else 0 for t in tid_list]
        now_ts = time.time()
        active_now = set()
        for i, tid in enumerate(tids_by_index):
            if tid == 0:
                continue
            active_now.add(tid)
            det = detections[i]
            emb = emb_by_index[i] if i < len(emb_by_index) else np.zeros(0, dtype=np.float32)
            attrs = attrs_by_index[i] if i < len(attrs_by_index) else {}
            if tid not in self._states:
                self._states[tid] = _TrackState(tid, det.class_name, ts, emb, attrs)
            else:
                st = self._states[tid]
                st.embs.append(emb)
                st.frame_count += 1
                st.end_ts = ts
                st.last_seen = now_ts
                for k, v in attrs.items():
                    st.attrs[k] = v  # last wins; color/class are stable
            if reid_by_index and i < len(reid_by_index):
                rid = reid_by_index[i]
                if rid is not None and rid.ndim == 1 and rid.size:
                    self._states[tid].reid_embs.append(rid)

        finalized = 0
        for tid in [t for t in self._states if t not in active_now]:
            st = self._states[tid]
            if now_ts - st.last_seen > TRACK_FINALIZE_SECONDS:
                if self.persist:
                    self._persist_track(st, closed=True)
                del self._states[tid]
                finalized += 1

        if self.persist and now_ts - self._last_persist >= TRACK_PERSIST_INTERVAL:
            self._last_persist = now_ts
            for st in self._states.values():
                self._persist_track(st, closed=False)
        return finalized, len(self._states), tids_by_index

    def _finalize_stale(self, ts: datetime) -> int:
        now_ts = time.time()
        dead = [t for t, st in self._states.items() if now_ts - st.last_seen > TRACK_FINALIZE_SECONDS]
        for tid in dead:
            st = self._states.pop(tid)
            if self.persist:
                self._persist_track(st, closed=True)
        return len(dead)

    def _persist_track(self, st: _TrackState, closed: bool) -> None:
        try:
            from app.db.base import SessionLocal
            from app.db.models import Tracklet

            db = SessionLocal()
            try:
                row = (
                    db.query(Tracklet)
                    .filter(Tracklet.camera_id == self.camera_id, Tracklet.local_track_id == st.track_id)
                    .first()
                )
                mean = _mean_emb(st.embs)
                reid = _mean_emb(st.reid_embs)
                if row is None:
                    row = Tracklet(
                        camera_id=self.camera_id,
                        local_track_id=st.track_id,
                        object_class=st.object_class,
                        start_ts=st.start_ts,
                        end_ts=st.end_ts,
                        frame_count=st.frame_count,
                        mean_embedding=_b64(mean),
                        reid_embedding=_b64(reid) if reid.size else "",
                        attrs_json=st.attrs,
                    )
                    db.add(row)
                else:
                    row.object_class = st.object_class
                    row.start_ts = min(_as_aware(row.start_ts), st.start_ts)
                    row.end_ts = max(_as_aware(row.end_ts), st.end_ts)
                    row.frame_count = st.frame_count
                    row.mean_embedding = _b64(mean)
                    row.reid_embedding = _b64(reid) if reid.size else row.reid_embedding
                    row.attrs_json = st.attrs
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 - tracklets are best-effort
            logger.debug("[cam %s] tracklet persist failed: %s", self.camera_id, exc)

    def active_track_count(self) -> int:
        return len(self._states)
