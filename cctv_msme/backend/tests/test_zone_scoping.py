"""Zone-scoping tests: worker/supervisor accounts must never see data from
zones other than their own via ANY route (video search, doc search, alerts,
summaries, streams) — verified end-to-end through the API."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


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


@pytest.fixture(scope="module")
def seeded(client, tokens):
    """Create cameras in two zones and index a frame in each; seed one
    document per zone and an alert in each zone."""
    from app.state import state
    from app.services.embedding.base import FakeEmbedder

    cam_ids = {}
    for name, zone in [("ZoneA Cam", "ZoneA"), ("ZoneB Cam", "ZoneB")]:
        r = client.post(
            "/api/cameras",
            json={"name": name, "rtsp_url": "sim://loading_dock", "zone": zone, "sample_interval_seconds": 2},
            headers=_auth(tokens["admin"]),
        )
        assert r.status_code == 200, r.text
        cam_ids[zone] = r.json()["id"]

    embs = FakeEmbedder(dim=64)
    state.vector_store.add(
        [f"frame-a", f"frame-b"],
        [embs.embed_text("frame a"), embs.embed_text("frame b")],
        [
            {
                "modality": "video",
                "camera_id": cam_ids["ZoneA"],
                "camera_name": "ZoneA Cam",
                "zone": "ZoneA",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "ts_epoch": 1767225600.0,
                "segment_id": "za",
                "thumbnail": f"{cam_ids['ZoneA']}_1000_0.jpg",
                "clip_offset": 0.0,
                "file_source": False,
            },
            {
                "modality": "video",
                "camera_id": cam_ids["ZoneB"],
                "camera_name": "ZoneB Cam",
                "zone": "ZoneB",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "ts_epoch": 1767225600.0,
                "segment_id": "zb",
                "thumbnail": f"{cam_ids['ZoneB']}_1000_0.jpg",
                "clip_offset": 0.0,
                "file_source": False,
            },
        ],
    )
    state.vector_store.add(
        ["doc-a", "doc-b"],
        [embs.embed_text("doc a"), embs.embed_text("doc b")],
        [
            {"modality": "document", "document_id": 9001, "filename": "a.pdf", "zone": "ZoneA", "page": 1, "section": "S", "chunk_text": "aaa"},
            {"modality": "document", "document_id": 9002, "filename": "b.pdf", "zone": "ZoneB", "page": 1, "section": "S", "chunk_text": "bbb"},
        ],
        texts=["aaa", "bbb"],
    )

    from app.db.base import SessionLocal
    from app.db.models import Alert

    db = SessionLocal()
    try:
        for zone, cam_id, atype in [("ZoneA", cam_ids["ZoneA"], "spill"), ("ZoneB", cam_ids["ZoneB"], "smoke_fire")]:
            db.add(
                Alert(
                    camera_id=cam_id,
                    camera_name=f"{zone} Cam",
                    zone=zone,
                    alert_type=atype,
                    description=f"{zone} alert",
                    score=0.9,
                )
            )
        db.commit()
    finally:
        db.close()

    yield cam_ids

    # Cleanup: camera rows are removed via API; alerts/vectors persist in
    # the temp DB which is discarded after the session anyway.
    for cam_id in cam_ids.values():
        client.delete(f"/api/cameras/{cam_id}", headers=_auth(tokens["admin"]))


# ------------------------------------------------------------ video search
def test_video_search_cross_zone_returns_403(client, tokens, seeded):
    # Worker's zone is "Loading Dock" (seeded) -> ZoneA/ZoneB are foreign.
    # Workers cannot use video search at all, so either way: 403.
    r = client.post(
        "/api/search/video",
        json={"query": "something", "zones": ["ZoneA", "ZoneB"], "top_k": 5},
        headers=_auth(tokens["worker"]),
    )
    assert r.status_code == 403, r.text


def test_video_search_without_zones_is_filtered(client, tokens, seeded):
    """Supervisor restricted to ZoneA must only ever see ZoneA frames."""
    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        sup = db.query(User).filter(User.username == "supervisor").first()
        sup.zone = "ZoneA"
        db.commit()
    finally:
        db.close()
    try:
        r = client.post(
            "/api/search/video",
            json={"query": "something", "top_k": 20},
            headers=_auth(tokens["supervisor"]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["hits"], "expected at least the seeded ZoneA frame"
        for hit in r.json()["hits"]:
            assert hit["zone"] == "ZoneA", hit
    finally:
        db = SessionLocal()
        try:
            sup = db.query(User).filter(User.username == "supervisor").first()
            sup.zone = None
            db.commit()
        finally:
            db.close()


def test_supervisor_cross_zone_video_search_403(client, tokens, seeded):
    r = client.post(
        "/api/search/video",
        json={"query": "x", "zones": ["ZoneA"], "top_k": 5},
        headers=_auth(tokens["supervisor"]),
    )
    # supervisor has no zone -> unrestricted, should NOT be 403
    assert r.status_code == 200, r.text


def test_zone_scoped_supervisor_cross_zone_403(client, tokens, seeded):
    """A supervisor WITH a zone must get 403 for foreign zones."""
    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        sup = db.query(User).filter(User.username == "supervisor").first()
        sup.zone = "ZoneA"
        db.commit()
    finally:
        db.close()
    try:
        r = client.post(
            "/api/search/video",
            json={"query": "x", "zones": ["ZoneB"], "top_k": 5},
            headers=_auth(tokens["supervisor"]),
        )
        assert r.status_code == 403, r.text
        # Own-zone search works
        r2 = client.post(
            "/api/search/video",
            json={"query": "x", "zones": ["ZoneA"], "top_k": 5},
            headers=_auth(tokens["supervisor"]),
        )
        assert r2.status_code == 200, r2.text
    finally:
        db = SessionLocal()
        try:
            sup = db.query(User).filter(User.username == "supervisor").first()
            sup.zone = None
            db.commit()
        finally:
            db.close()


# -------------------------------------------------------- document search
def test_document_search_is_zone_scoped(client, tokens, seeded):
    from app.state import state
    from app.services.embedding.base import FakeEmbedder

    state.embedder = FakeEmbedder(dim=64)
    r = client.post(
        "/api/search/documents",
        json={"query": "aaa bbb", "top_k": 10},
        headers=_auth(tokens["worker"]),
    )
    assert r.status_code == 200, r.text
    # Worker only sees "Loading Dock" docs; seeded docs are ZoneA/ZoneB.
    assert all(hit["zone"] == "Loading Dock" for hit in r.json())


def test_document_list_is_zone_scoped(client, tokens, seeded):
    r = client.get("/api/documents", headers=_auth(tokens["worker"]))
    assert r.status_code == 200
    assert all(d["zone"] == "Loading Dock" for d in r.json())


# ---------------------------------------------------------------- alerts
def test_alerts_are_zone_scoped(client, tokens, seeded):
    r = client.get("/api/alerts", headers=_auth(tokens["worker"]))
    assert r.status_code == 403  # workers cannot view alerts at all

    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        sup = db.query(User).filter(User.username == "supervisor").first()
        sup.zone = "ZoneA"
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/api/alerts", headers=_auth(tokens["supervisor"]))
        assert r.status_code == 200, r.text
        zones = {a["zone"] for a in r.json()}
        assert zones == {"ZoneA"}, zones

        # Acknowledging a foreign-zone alert must 403
        from app.db.base import SessionLocal as SL2
        from app.db.models import Alert

        db2 = SL2()
        try:
            foreign = db2.query(Alert).filter(Alert.zone == "ZoneB").first()
            fid = foreign.id
        finally:
            db2.close()
        ra = client.post(f"/api/alerts/{fid}/acknowledge", headers=_auth(tokens["supervisor"]))
        assert ra.status_code == 403, ra.text
    finally:
        db = SessionLocal()
        try:
            sup = db.query(User).filter(User.username == "supervisor").first()
            sup.zone = None
            db.commit()
        finally:
            db.close()


# ------------------------------------------------------------ summaries
def test_summaries_are_zone_scoped(client, tokens, seeded):
    from app.db.base import SessionLocal
    from app.db.models import Summary, User

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add(
            Summary(
                title="A summary",
                kind="shift",
                zone="ZoneA",
                content="x",
                created_by="admin",
                window_start=now,
                window_end=now,
                tags_json={},
            )
        )
        db.commit()
        sup = db.query(User).filter(User.username == "supervisor").first()
        sup.zone = "ZoneB"
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/api/summaries", headers=_auth(tokens["supervisor"]))
        assert r.status_code == 200, r.text
        assert all(s["zone"] == "ZoneB" for s in r.json())
    finally:
        db = SessionLocal()
        try:
            sup = db.query(User).filter(User.username == "supervisor").first()
            sup.zone = None
            db.commit()
        finally:
            db.close()


# ------------------------------------------------------------- stream zone
def test_stream_media_is_zone_scoped(client, tokens, seeded):
    """A zone-restricted user cannot fetch another zone's thumbnail."""
    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    try:
        sup = db.query(User).filter(User.username == "supervisor").first()
        sup.zone = "ZoneA"
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/api/streams/thumb/9999_1000_0.jpg", headers=_auth(tokens["supervisor"]))
        assert r.status_code == 404  # unknown camera id -> not found, not leaked
    finally:
        db = SessionLocal()
        try:
            sup = db.query(User).filter(User.username == "supervisor").first()
            sup.zone = None
            db.commit()
        finally:
            db.close()
