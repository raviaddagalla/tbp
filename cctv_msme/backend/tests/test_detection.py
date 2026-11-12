"""Phase 1: detection, tracking, attributes and entity search."""
from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.db.models import Camera


# ------------------------------------------------------------ fixtures
class FakeDetection:
    def __init__(self, xyxy, confidence=0.9, class_name="person", class_id=0):
        self.xyxy = xyxy
        self.confidence = confidence
        self.class_name = class_name
        self.class_id = class_id
        h = max(4, int(xyxy[3] - xyxy[1]))
        w = max(4, int(xyxy[2] - xyxy[0]))
        self.crop = np.full((h, w, 3), 100, dtype=np.uint8)


class FakeDetector:
    def __init__(self, detections):
        self.detections = detections

    def detect(self, frame_bgr):
        return list(self.detections)


class FakeWorker:
    """Minimal stand-in for CameraWorker.__init__ side effects."""

    camera_id = 1


def _emb(v: float) -> np.ndarray:
    a = np.zeros(64, dtype=np.float32)
    a[0] = v
    n = np.linalg.norm(a)
    return (a / n).astype(np.float32) if n else a


def _fake_embedder():
    from app.services.embedding.base import FakeEmbedder

    return FakeEmbedder(dim=64)


@pytest.fixture(scope="module", autouse=True)
def _cleanup_cameras(client):
    """Direct DB inserts don't go through the API, so remove them at module
    end — otherwise later modules' lifespans start workers for them."""
    yield
    from app.db.base import SessionLocal
    from app.db.models import Camera, Tracklet

    db = SessionLocal()
    try:
        rows = db.query(Camera).filter(Camera.name.in_(["TrackletTest", "ObjTest", "T"])).all()
        ids = [r.id for r in rows]
        db.query(Tracklet).filter(Tracklet.camera_id.in_(ids)).delete(synchronize_session=False)
        for r in rows:
            db.delete(r)
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.state import state

    with TestClient(app) as c:
        state.embedder = _fake_embedder()
        if state.anomaly_detector is not None:
            state.anomaly_detector.embedder = state.embedder
        if state.worker_manager is not None:
            state.worker_manager.embedder = state.embedder
            for w in state.worker_manager.workers.values():
                w.embedder = state.embedder
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------ attributes
def test_extract_attributes_returns_known_keys():
    from app.services.detection.attributes import extract_attributes

    attrs = extract_attributes(_fake_embedder(), _emb(0.5), "person")
    assert set(attrs) == {"attr_color", "attr_clothing", "attr_ppe"}
    assert attrs["attr_color"] in {
        "red", "orange", "yellow", "green", "blue", "purple", "pink",
        "white", "black", "gray", "brown",
    }
    # Non-person objects don't get clothing/ppe attributes
    truck = extract_attributes(_fake_embedder(), _emb(0.5), "truck")
    assert truck["attr_clothing"] == "n/a"
    assert truck["attr_ppe"] == "n/a"


# ------------------------------------------------------------ tracking
def test_tracker_assigns_stable_ids_and_persists_tracklets(client, tmp_path, monkeypatch):
    from app.db.base import SessionLocal
    from app.db.models import Tracklet
    from app.services.detection.tracker import TrackletTracker

    db = SessionLocal()
    try:
        cam = db.query(Camera).filter(Camera.name == "ZoneA Cam").first()
        if cam is None:
            cam = Camera(name="TrackletTest", rtsp_url="sim://x", zone="General")
            db.add(cam)
            db.commit()
            db.refresh(cam)
        cam_id = cam.id
    finally:
        db.close()

    tracker = TrackletTracker(camera_id=cam_id, persist=True, frame_rate=5)
    ts = datetime.now(timezone.utc)
    dets = [FakeDetection((10, 10, 60, 90)), FakeDetection((200, 50, 300, 200), class_name="forklift", class_id=7)]
    _, _, tids1 = tracker.update(dets, ts, [_emb(0.1), _emb(0.2)], [{"attr_color": "blue"}, {"attr_color": "red"}])
    assert len(set(tids1)) == 2 and all(t > 0 for t in tids1)

    # Same positions again -> same track ids (stable identity)
    _, _, tids2 = tracker.update(dets, ts + timedelta(seconds=1), [_emb(0.1), _emb(0.2)], [{}, {}])
    assert tids2 == tids1

    # Walk away -> track finalized after the grace period (wall-clock based)
    from app.services.detection.tracker import TRACK_FINALIZE_SECONDS

    time.sleep(TRACK_FINALIZE_SECONDS + 0.5)
    tracker.update([], ts + timedelta(seconds=5), [], [])
    assert tracker.active_track_count() == 0

    db = SessionLocal()
    try:
        rows = db.query(Tracklet).filter(Tracklet.camera_id == cam_id).all()
    finally:
        db.close()
    assert len(rows) == 2
    by_class = {r.object_class: r for r in rows}
    assert "person" in by_class and "forklift" in by_class
    person = by_class["person"]
    assert person.frame_count >= 2
    mean = np.frombuffer(base64.b64decode(person.mean_embedding), dtype=np.float32)
    assert mean.shape == (64,)
    assert person.attrs_json.get("attr_color") == "blue"


# ------------------------------------------------------------ detection path
def test_worker_indexes_object_rows_and_tracks(client, tmp_path, monkeypatch):
    """End-to-end: detection -> per-object CLIP embedding -> vector rows +
    tracklet rows, wired through CameraWorker._index_objects."""
    from app.db.base import SessionLocal
    from app.db.models import Tracklet
    from app.services.ingestion.camera_worker import CameraWorker

    db = SessionLocal()
    try:
        cam = Camera(name="ObjTest", rtsp_url="sim://x", zone="ZoneA", detector_enabled=True)
        db.add(cam)
        db.commit()
        db.refresh(cam)
    finally:
        db.close()

    embedder = _fake_embedder()

    from app.services.detection.tracker import TrackletTracker
    from app.services.vectorstore.numpy_store import NumpyStore

    store = NumpyStore(str(tmp_path / "vs"))
    worker = CameraWorker.__new__(CameraWorker)
    worker.camera = cam
    worker.embedder = embedder
    worker.vector_store = store
    worker.detector = FakeDetector([FakeDetection((5, 5, 80, 100)), FakeDetection((300, 100, 450, 300), class_id=7)])
    worker._detector_resolved = True
    worker.tracker = TrackletTracker(camera_id=cam.id, persist=True, frame_rate=5)
    worker._tracker_lock = __import__("threading").Lock()
    worker._is_file_source = False
    worker._save_thumb = lambda img, name: None

    ts = datetime.now(timezone.utc)
    worker._index_objects(
        np.zeros((480, 640, 3), dtype=np.uint8),
        ts,
        seq=3,
        segment_id="seg1",
        offset=1.5,
        frame_id="f-1",
        frame_thumb_rel="thumbs/frame.jpg",
    )

    hits = store.get(filters={"modality": "object"})
    assert len(hits) == 2
    m0 = hits[0].metadata
    assert m0["object_class"] == "person"
    assert m0["parent_frame_id"] == "f-1"
    assert m0["tracklet_local_id"] > 0
    assert m0["bbox"].count(",") == 3
    assert m0["attr_color"] in {"red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "black", "gray", "brown"}

    db = SessionLocal()
    try:
        tracks = db.query(Tracklet).filter(Tracklet.camera_id == cam.id).count()
    finally:
        db.close()
    assert tracks >= 1


# ------------------------------------------------------------ entity search
def test_entity_search_endpoint_filters_and_returns_metadata(client, admin_token):
    from app.state import state

    embs = _fake_embedder()
    r = client.post(
        "/api/cameras",
        json={"name": "EntityCam", "rtsp_url": "sim://x", "zone": "ZoneA", "detector_enabled": False},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    cam_id = r.json()["id"]

    now = datetime.now(timezone.utc)
    state.vector_store.add(
        ["obj-1", "obj-2"],
        [embs.embed_text("a person in a red jacket"), embs.embed_text("a forklift")],
        [
            {
                "modality": "object",
                "camera_id": cam_id,
                "camera_name": "EntityCam",
                "zone": "ZoneA",
                "timestamp": now.isoformat(),
                "ts_epoch": now.timestamp(),
                "segment_id": "seg1",
                "clip_offset": 2.0,
                "file_source": False,
                "parent_frame_id": "f-1",
                "object_class": "person",
                "bbox": "0.1,0.2,0.3,0.4",
                "detection_confidence": 0.95,
                "tracklet_local_id": 5,
                "thumbnail": "thumbs/1_2_3_o0_0.jpg",
                "frame_thumbnail": "thumbs/1_2_3.jpg",
                "attr_color": "red",
                "attr_clothing": "a person wearing a high-visibility safety vest",
                "attr_ppe": "n/a",
            },
            {
                "modality": "object",
                "camera_id": cam_id,
                "camera_name": "EntityCam",
                "zone": "ZoneA",
                "timestamp": now.isoformat(),
                "ts_epoch": now.timestamp(),
                "segment_id": "seg1",
                "clip_offset": 2.0,
                "file_source": False,
                "parent_frame_id": "f-1",
                "object_class": "forklift",
                "bbox": "0.5,0.5,0.6,0.6",
                "detection_confidence": 0.8,
                "tracklet_local_id": 6,
                "thumbnail": "thumbs/1_2_3_o7_1.jpg",
                "frame_thumbnail": "thumbs/1_2_3.jpg",
                "attr_color": "yellow",
                "attr_clothing": "n/a",
                "attr_ppe": "n/a",
            },
        ],
    )

    r = client.post(
        "/api/search/entities",
        json={"query": "person", "object_class": "person", "top_k": 10},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    hit = r.json()["hits"][0]
    assert hit["object_class"] == "person"
    assert hit["bbox"] == "0.1,0.2,0.3,0.4"
    assert hit["attrs"]["color"] == "red"
    assert hit["thumbnail_url"].startswith("/api/streams/thumb/")
    assert hit["tracklet_local_id"] == 5

    # Zone-restricted worker is blocked from entity search entirely (roles)
    worker = client.post("/api/auth/login", json={"username": "worker", "password": "worker123"})
    assert worker.status_code == 200
    rw = client.post(
        "/api/search/entities",
        json={"query": "person", "top_k": 5},
        headers=_auth(worker.json()["access_token"]),
    )
    assert rw.status_code == 403

    client.delete(f"/api/cameras/{cam_id}", headers=_auth(admin_token))
