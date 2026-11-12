"""Smoke tests: auth/RBAC, document ingestion, doc search, mock RAG, pipeline."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.services.embedding.base import FakeEmbedder

    from app.state import state

    with TestClient(app) as c:
        # Swap CLIP for a deterministic fake embedder AFTER lifespan init:
        # tests must not download model weights.
        state.embedder = FakeEmbedder(dim=64)
        if state.anomaly_detector is not None:
            state.anomaly_detector.embedder = state.embedder
        if state.worker_manager is not None:
            state.worker_manager.embedder = state.embedder
            # Workers built during lifespan hold the real CLIP embedder;
            # repoint them so leftover cameras never embed at 512-dim.
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


# ---------------------------------------------------------------- auth/RBAC
def test_login_and_roles(client, tokens):
    assert tokens["admin"] and tokens["supervisor"] and tokens["worker"]

    r = client.get("/api/auth/me", headers=_auth(tokens["admin"]))
    assert r.status_code == 200 and r.json()["role"] == "admin"

    r = client.get("/api/auth/me", headers=_auth("garbage-token"))
    assert r.status_code == 401

    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_role_enforcement(client, tokens):
    # Worker cannot search video or manage cameras
    r = client.post("/api/search/video", json={"query": "forklift"}, headers=_auth(tokens["worker"]))
    assert r.status_code == 403

    r = client.post("/api/cameras", json={"name": "x", "rtsp_url": "sim://loading_dock"}, headers=_auth(tokens["worker"]))
    assert r.status_code == 403

    r = client.post("/api/cameras", json={"name": "x", "rtsp_url": "sim://loading_dock"}, headers=_auth(tokens["supervisor"]))
    assert r.status_code == 403

    r = client.get("/api/users", headers=_auth(tokens["worker"]))
    assert r.status_code == 403


# ---------------------------------------------------------------- cameras
def test_camera_crud_and_health(client, tokens):
    r = client.post(
        "/api/cameras",
        json={"name": "Test Dock", "rtsp_url": "sim://loading_dock", "zone": "Logistics"},
        headers=_auth(tokens["admin"]),
    )
    assert r.status_code == 200, r.text
    cam = r.json()
    cam_id = cam["id"]

    r = client.get("/api/cameras", headers=_auth(tokens["admin"]))
    assert any(c["id"] == cam_id for c in r.json())

    # Worker scoped to "Loading Dock" zone must NOT see this Logistics camera
    r = client.get("/api/cameras", headers=_auth(tokens["worker"]))
    assert all(c["id"] != cam_id for c in r.json())

    r = client.patch(f"/api/cameras/{cam_id}", json={"name": "Test Dock 2"}, headers=_auth(tokens["admin"]))
    assert r.status_code == 200 and r.json()["name"] == "Test Dock 2"

    r = client.delete(f"/api/cameras/{cam_id}", headers=_auth(tokens["admin"]))
    assert r.status_code == 200


def test_camera_health_updates_with_sim(client, tokens):
    """The sim:// camera worker should flip status to online and index frames."""
    r = client.post(
        "/api/cameras",
        json={"name": "Sim Cam", "rtsp_url": "sim://storage", "zone": "Warehouse", "sample_interval_seconds": 2},
        headers=_auth(tokens["admin"]),
    )
    assert r.status_code == 200
    cam_id = r.json()["id"]
    health = {}
    for _ in range(15):
        r = client.get(f"/api/cameras/{cam_id}/health", headers=_auth(tokens["admin"]))
        health = r.json()
        if health["status"] == "online" and health["frames_indexed"] > 0:
            break
        time.sleep(1)
    assert health["status"] == "online", health
    assert health["frames_indexed"] > 0, health
    client.delete(f"/api/cameras/{cam_id}", headers=_auth(tokens["admin"]))


def test_analytics_overview_ok(client, tokens):
    """Dashboard endpoint must not 500: document_usage is a list of dicts."""
    r = client.get("/api/analytics/overview", headers=_auth(tokens["admin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["chunks_indexed"], int)
    assert isinstance(body["cameras_total"], int)
    assert all(isinstance(d, dict) for d in body["document_usage"])


def test_websocket_events_handshake(client, tokens):
    """The live-event WebSocket must accept a scoped media token (as the SPA
    does — cookies can't be sent on cross-origin handshakes)."""
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    r = client.post("/api/auth/media-token", json={"path": "/api/ws/events"}, headers=headers)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    with client.websocket_connect(f"/api/ws/events?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "activity_history"


def test_websocket_rejects_invalid_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/ws/events?token=bogus") as ws:
            ws.receive_json()


# ---------------------------------------------------------------- documents
def test_document_ingestion_and_search(client, tokens):
    import fitz

    from app.state import state
    from app.services.embedding.base import FakeEmbedder

    # Override CLIP with a deterministic fake for fast tests
    state.embedder = FakeEmbedder(dim=64)

    pdf_path = f"{state.settings.data_dir}/sample_sop.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Forklift Safety Procedure - Loading Dock Zone")
    page.insert_text((72, 130), "Always wear a safety helmet when operating the forklift.")
    page.insert_text((72, 170), "Do not enter the restricted area behind the dock door.")
    doc.save(pdf_path)
    doc.close()

    with open(pdf_path, "rb") as f:
        r = client.post(
            "/api/documents",
            files={"file": ("sample_sop.pdf", f, "application/pdf")},
            headers=_auth(tokens["admin"]),
        )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    processed = None
    for _ in range(30):
        r = client.get("/api/documents", headers=_auth(tokens["admin"]))
        processed = next((d for d in r.json() if d["id"] == doc_id), None)
        if processed and processed["status"] == "processed":
            break
        time.sleep(0.5)
    assert processed and processed["status"] == "processed", processed
    assert processed["chunk_count"] >= 1

    r = client.post("/api/search/documents", json={"query": "forklift safety", "top_k": 5}, headers=_auth(tokens["admin"]))
    assert r.status_code == 200, r.text
    hits = r.json()
    assert len(hits) >= 1
    assert hits[0]["document_id"] == doc_id


# ---------------------------------------------------------------- mock RAG
def test_mock_rag_grounding(client, tokens):
    from app.services.rag.llm.mock import DONT_KNOW, MockLLM
    from app.services.rag.orchestrator import RagOrchestrator
    from app.state import state

    # Self-contained: index one known chunk, then verify grounded retrieval
    texts = ["Always wear a safety helmet when operating the forklift at the loading dock."]
    embs = state.embedder.embed_texts(texts)
    state.vector_store.add(
        ["rag-test-chunk"],
        embs,
        [{"modality": "document", "document_id": 999, "filename": "sop.pdf", "page": 2, "section": "Forklift", "chunk_idx": 0, "chunk_text": texts[0]}],
        texts=texts,
    )

    orch = RagOrchestrator(state.llm, state.embedder, state.vector_store)

    # Grounded: indexed chunk matches the question
    res = orch.answer_question("What is the safety procedure for the forklift?")
    assert res["intent"]["doc"] is True
    assert "Based on the available documents" in res["answer"]
    assert any(c["filename"] == "sop.pdf" for c in res["citations"])

    # Mock refusal path: no context -> explicit "don't know", no hallucination
    m = MockLLM()
    no_ctx = m.chat("", "QUESTION: calibrate the CNC lathe\nCONTEXT DOCUMENTS:\n")
    assert DONT_KNOW in no_ctx
    with_ctx = m.chat("", "QUESTION: x\nCONTEXT DOCUMENTS:\n- [manual.pdf - page 2 | section: S] Always lockout.\n")
    assert DONT_KNOW not in with_ctx and "lockout" in with_ctx

    # Video intent routing
    res3 = orch.answer_question("Show me the forklift near the loading dock")
    assert res3["intent"]["video"] is True


def test_chunker():
    from app.services.documents.chunker import chunk_pages
    from app.services.documents.parser import PageText

    pages = [
        PageText(page=1, heading="Introduction", text="a" * 300),
        PageText(page=2, heading="Safety Rules", text="b" * 300 + "\n\n" + "c" * 300),
    ]
    chunks = chunk_pages(pages, chunk_size=200, overlap=50)
    assert len(chunks) >= 3
    assert chunks[0].section == "Introduction"
    assert any(c.section == "Safety Rules" for c in chunks)
    assert any("b" * 100 in c.text for c in chunks)
    assert any("c" * 100 in c.text for c in chunks)


def test_sim_source_frames():
    import numpy as np

    from app.services.ingestion.sources import SimulatedCameraSource

    src = SimulatedCameraSource("loading_dock", "t")
    assert src.open()
    ok, frame = src.read()
    assert ok and frame.shape == (540, 960, 3)
    assert frame.dtype == np.uint8
    src.release()


def test_video_file_source_eof(tmp_path):
    """VideoFileSource reads a real mp4 to EOF then reports finished."""
    import cv2
    import numpy as np

    from app.services.ingestion.sources import VideoFileSource

    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for i in range(25):
        writer.write(np.full((180, 320, 3), i * 8, dtype=np.uint8))
    writer.release()

    src = VideoFileSource(path, "t")
    assert src.open()
    frames = 0
    while True:
        ok, frame = src.read()
        if not ok:
            break
        frames += 1
        assert frame is not None and frame.shape == (180, 320, 3)
    assert frames == 25
    assert src.finished
    src.release()


def test_video_footage_upload_and_index(client, tokens):
    """Admin uploads a footage file -> file:// camera -> frames indexed at 2 fps."""
    import cv2
    import numpy as np

    import pytest

    pytest.importorskip("cv2")
    path = f"{getattr(__import__('app.state', fromlist=['state']).state.settings, 'data_dir')}/upload_test.mp4"
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for i in range(40):
        writer.write(np.full((180, 320, 3), (i * 5) % 255, dtype=np.uint8))
    writer.release()

    with open(path, "rb") as f:
        r = client.post(
            "/api/cameras/upload",
            files={"file": ("upload_test.mp4", f, "video/mp4")},
            data={"name": "Old Dock Footage", "zone": "Logistics"},
            headers=_auth(tokens["admin"]),
        )
    assert r.status_code == 200, r.text
    cam = r.json()
    assert cam["rtsp_url"].startswith("file://")
    assert cam["sample_interval_seconds"] == 0.2  # 5 fps default

    health = {}
    for _ in range(20):
        r = client.get(f"/api/cameras/{cam['id']}/health", headers=_auth(tokens["admin"]))
        health = r.json()
        if health["frames_indexed"] >= 5:
            break
        time.sleep(0.5)
    assert health["frames_indexed"] >= 5, health

    client.delete(f"/api/cameras/{cam['id']}", headers=_auth(tokens["admin"]))
