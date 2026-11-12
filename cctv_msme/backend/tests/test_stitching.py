"""Phase 2: cross-camera tracklet stitching over the adjacency graph."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient


def _b64(emb: np.ndarray) -> str:
    return base64.b64encode(np.asarray(emb, dtype=np.float32).tobytes()).decode("ascii")


def _reid(v: float, dim: int = 512) -> np.ndarray:
    a = np.zeros(dim, dtype=np.float32)
    a[0] = v
    n = np.linalg.norm(a)
    return (a / n).astype(np.float32) if n else a


def _mk(db, camera_name: str, zone: str = "Logistics") -> int:
    from app.db.models import Camera

    cam = Camera(name=camera_name, rtsp_url="sim://test", zone=zone, sample_interval_seconds=0.2)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam.id


def _mk_tracklet(db, camera_id: int, end_ts: datetime, reid: np.ndarray, local_id: int = 1, cls: str = "person"):
    from app.db.models import Tracklet

    t = Tracklet(
        camera_id=camera_id,
        local_track_id=local_id,
        object_class=cls,
        start_ts=end_ts - timedelta(seconds=10),
        end_ts=end_ts,
        frame_count=5,
        mean_embedding=_b64(np.ones(64, dtype=np.float32)),
        reid_embedding=_b64(reid),
        attrs_json={},
    )
    db.add(t)
    db.commit()
    return t.id


def _mk_edge(db, from_cam: int, to_cam: int, lo: int = 30, hi: int = 120):
    from app.db.models import CameraAdjacency

    db.add(
        CameraAdjacency(
            from_camera_id=from_cam,
            to_camera_id=to_cam,
            expected_transit_seconds_min=lo,
            expected_transit_seconds_max=hi,
        )
    )
    db.commit()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.state import state

    with TestClient(app) as c:
        if state.worker_manager is not None:
            for w in state.worker_manager.workers.values():
                w.embedder = state.embedder
        yield c


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    from app.db.base import SessionLocal
    from app.db.models import Camera, CameraAdjacency, Tracklet

    yield
    db = SessionLocal()
    try:
        db.query(CameraAdjacency).delete(synchronize_session=False)
        db.query(Tracklet).filter(Tracklet.camera_id.in_([9001, 9002, 9003, 9004])).delete(
            synchronize_session=False
        )
        db.query(Camera).filter(Camera.id.in_([9001, 9002, 9003, 9004])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def graph(client):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        a = _mk(db, "StitchA", "Logistics")
        b = _mk(db, "StitchB", "Logistics")
        c = _mk(db, "StitchC", "Logistics")  # not adjacent to A
        d = _mk(db, "StitchD", "Warehouse")  # adjacent to B
        _mk_edge(db, a, b, lo=30, hi=120)
        _mk_edge(db, b, d, lo=60, hi=240)
        return {"a": a, "b": b, "c": c, "d": d}
    finally:
        db.close()


def _stitch(source_camera_id, ts, **kw):
    from app.db.base import SessionLocal
    from app.services.reid.stitching import stitch_trail

    db = SessionLocal()
    try:
        return stitch_trail(db, source_camera_id, ts, **kw)
    finally:
        db.close()


def test_stitch_only_adjacent_cameras(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        t0 = datetime(2026, 8, 1, 10, 0, 0)
        _mk_tracklet(db, graph["a"], t0, _reid(1.0))
        # B within the 30-120s transit window; C is far away and NOT adjacent
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=60), _reid(1.0))
        _mk_tracklet(db, graph["c"], t0 + timedelta(seconds=60), _reid(1.0))
    finally:
        db.close()

    steps = _stitch(graph["a"], t0 + timedelta(seconds=5))
    cams = {s["camera_id"] for s in steps}
    assert graph["b"] in cams, "adjacent camera must be suggested"
    assert graph["c"] not in cams, "non-adjacent camera must NEVER be suggested"
    assert all(s["camera_name"] for s in steps)


def test_stitch_respects_transit_window(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        t0 = datetime(2026, 8, 2, 10, 0, 0)
        _mk_tracklet(db, graph["a"], t0, _reid(1.0))
        # arrives 1000s later — far outside the 30-120s window
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=1000), _reid(1.0), local_id=7)
    finally:
        db.close()

    steps = _stitch(graph["a"], t0 + timedelta(seconds=5))
    assert not any(s["camera_id"] == graph["b"] for s in steps), "outside transit window must be excluded"


def test_stitch_scores_reid_and_decays_per_hop(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        t0 = datetime(2026, 8, 3, 10, 0, 0)
        _mk_tracklet(db, graph["a"], t0, _reid(1.0))
        # B1 matches perfectly; B2 is orthogonal (poor ReID similarity)
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=60), _reid(1.0), local_id=1)
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=75), _reid(0.0), local_id=2)
        # D reached from B1 within 60-240s window
        _mk_tracklet(db, graph["d"], t0 + timedelta(seconds=150), _reid(1.0), local_id=1)
    finally:
        db.close()

    steps = _stitch(graph["a"], t0 + timedelta(seconds=5))
    b_step = max((s for s in steps if s["camera_id"] == graph["b"]), key=lambda s: s["confidence"])
    assert b_step["reid_similarity"] == pytest.approx(1.0, abs=0.01)
    assert b_step["confidence"] > 0.6
    d = next(s for s in steps if s["camera_id"] == graph["d"])
    assert d["hop"] == 2
    assert d["confidence"] < b_step["confidence"], "confidence must decay per hop"
    assert all(s["confidence"] <= 1.0 for s in steps)


def test_stitch_excludes_low_reid_match(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        t0 = datetime(2026, 8, 4, 10, 0, 0)
        _mk_tracklet(db, graph["a"], t0, _reid(1.0))
        # zero ReID similarity + perfect time fit => 0.667 * 0.7 = 0.467
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=75), _reid(0.0), local_id=3)
    finally:
        db.close()

    steps = _stitch(graph["a"], t0 + timedelta(seconds=5), min_confidence=0.5)
    assert not steps, "orthogonal ReID must be excluded by a higher min_confidence"


def test_stitch_empty_without_calibration(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        lone = _mk(db, "StitchLone", "Logistics")
        t0 = datetime(2026, 8, 5, 10, 0, 0)
        _mk_tracklet(db, lone, t0, _reid(1.0))
        # A source camera with no tracklet at all -> no trail
        _mk_tracklet(db, graph["d"], t0, _reid(1.0), local_id=9)
    finally:
        db.close()

    assert _stitch(lone, datetime(2026, 8, 5, 10, 0, 1)) == []
    # D has no outgoing adjacency edges -> nothing to follow
    assert _stitch(graph["d"], datetime(2026, 8, 5, 10, 0, 1)) == []


def test_track_movement_wrapper_returns_steps(client, graph):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        t0 = datetime(2026, 8, 6, 10, 0, 0)
        _mk_tracklet(db, graph["a"], t0, _reid(1.0))
        _mk_tracklet(db, graph["b"], t0 + timedelta(seconds=60), _reid(1.0), local_id=4)
    finally:
        db.close()

    from app.services.alerts.tracking import track_movement

    steps = track_movement(vector_store=None, frame_emb=None, source_camera_id=graph["a"], timestamp=t0 + timedelta(seconds=5))
    assert any(s["camera_id"] == graph["b"] for s in steps)
