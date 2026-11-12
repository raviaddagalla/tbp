"""Phase 3: batch reprocessing (temporal clip_event windows) + temporal search."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient


def _emb(v: float, dim: int = 64) -> np.ndarray:
    a = np.zeros(dim, dtype=np.float32)
    a[0] = v
    n = np.linalg.norm(a)
    return (a / n).astype(np.float32) if n else a


def _add_video_rows(store, camera_id: int, name: str, zone: str, segment: str, count: int, base_ts: float):
    ids, embs, metas = [], [], []
    for i in range(count):
        ts = base_ts + i * 0.2
        ids.append(f"v-{segment}-{i}")
        embs.append(_emb(float(i % 7)))
        metas.append(
            {
                "modality": "video",
                "camera_id": camera_id,
                "camera_name": name,
                "zone": zone,
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "ts_epoch": ts,
                "segment_id": segment,
                "thumbnail": f"thumbs/{camera_id}_0_{i}.jpg",
                "clip_offset": i * 0.2,
                "file_source": True,
            }
        )
    store.add(ids, embs, metas)


def test_reprocess_pools_windows_and_is_idempotent(client, tmp_path):
    from app.core.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import Camera
    from app.services.ingestion.batch_reprocessor import reprocess_camera
    from app.services.vectorstore.numpy_store import NumpyStore

    db = SessionLocal()
    cam = Camera(
        name="BatchCam",
        rtsp_url="file:///tmp/x.mp4",
        zone="Logistics",
        sample_interval_seconds=0.2,
        batch_reprocess_enabled=True,
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)

    store = NumpyStore(str(tmp_path / "vs"))
    old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    _add_video_rows(store, cam.id, "BatchCam", "Logistics", "s1", 32, old)
    _add_video_rows(store, cam.id, "BatchCam", "Logistics", "s2", 16, old + 100)

    settings = get_settings()
    stats = reprocess_camera(db, store, cam, settings)
    # s1 (32 rows): windows at starts 0,8,16 -> 3; s2 (16 rows): 1 window
    assert stats["windows_added"] == 4, stats

    rows = store.get(filters={"modality": "clip_event", "camera_id": cam.id})
    assert len(rows) == 4
    assert all(r.metadata["frame_count"] == 16 for r in rows)
    assert all(r.metadata["ts_epoch"] <= old + 100 + 16 * 0.2 for r in rows)
    assert all(np.allclose(np.linalg.norm(r.embedding), 1.0) for r in rows)

    again = reprocess_camera(db, store, cam, settings)
    assert again["windows_added"] == 0, "reprocessing must be idempotent"

    # frames newer than the age cutoff are untouched
    recent_ts = datetime.now(timezone.utc).timestamp() - 60
    _add_video_rows(store, cam.id, "BatchCam", "Logistics", "fresh", 20, recent_ts)
    stats2 = reprocess_camera(db, store, cam, settings)
    assert stats2["windows_added"] == 0, "recent footage must not be reprocessed"

    db.close()


def test_temporal_search_endpoint(client, tokens):
    from app.services.embedding.base import FakeEmbedder
    from app.state import state

    # camera via API (batch reprocess off to avoid background threads)
    r = client.post(
        "/api/cameras",
        json={
            "name": "TemporalCam",
            "rtsp_url": "file:///tmp/entry.mp4",
            "zone": "Logistics",
            "batch_reprocess_enabled": False,
        },
        headers=_auth(tokens["admin"]),
    )
    assert r.status_code == 200, r.text
    cam_id = r.json()["id"]

    store = state.vector_store
    old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    _add_video_rows(store, cam_id, "TemporalCam", "Logistics", "segA", 16, old)

    query_emb = state.embedder.embed_text("person entering the side door")
    evt_meta = {
        "modality": "clip_event",
        "camera_id": cam_id,
        "camera_name": "TemporalCam",
        "zone": "Logistics",
        "timestamp": datetime.fromtimestamp(old + 10, tz=timezone.utc).isoformat(),
        "ts_epoch": old + 10,
        "window_start": old,
        "window_end": old + 3,
        "frame_count": 16,
        "segment_id": "segA",
        "thumbnail": "thumbs/x.jpg",
        "clip_offset": 0.0,
        "file_source": True,
        "window_key": "segA:1",
    }
    store.add([f"evt-{i}" for i in range(3)], [query_emb] * 3, [dict(evt_meta)] * 3)

    r = client.post(
        "/api/search/temporal",
        json={"query": "person entering the side door", "top_k": 5},
        headers=_auth(tokens["worker"]),
    )
    assert r.status_code == 403, "worker must not run temporal search"

    r = client.post(
        "/api/search/temporal",
        json={"query": "person entering the side door", "top_k": 5},
        headers=_auth(tokens["supervisor"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["temporal_used"] is True
    assert len(body["hits"]) == 3
    top = body["hits"][0]
    assert top["frame_count"] == 16
    assert top["window_start"] is not None and top["window_end"] is not None
    assert top["camera_name"] == "TemporalCam"


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.services.embedding.base import FakeEmbedder

    from app.state import state

    with TestClient(app) as c:
        state.embedder = FakeEmbedder(dim=64)
        if state.anomaly_detector is not None:
            state.anomaly_detector.embedder = state.embedder
        if state.worker_manager is not None:
            state.worker_manager.embedder = state.embedder
            for w in state.worker_manager.workers.values():
                w.embedder = state.embedder
        yield c


@pytest.fixture(scope="module")
def tokens(client):
    out = {}
    for username, pw in [
        ("admin", "admin123"),
        ("supervisor", "supervisor123"),
        ("worker", "worker123"),
    ]:
        r = client.post("/api/auth/login", json={"username": username, "password": pw})
        assert r.status_code == 200, r.text
        out[username] = r.json()["access_token"]
    return out


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    from app.db.base import SessionLocal
    from app.db.models import Camera

    yield
    db = SessionLocal()
    try:
        db.query(Camera).filter(Camera.name.in_(["BatchCam", "TemporalCam"])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
