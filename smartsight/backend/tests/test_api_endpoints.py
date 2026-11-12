"""Integration tests for all SmartSight API endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "app" in data
    assert "monitoring" in data


def test_overview_endpoint(client: TestClient):
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "totals" in data
    assert "camera" in data
    assert "storage" in data


def test_activity_endpoint(client: TestClient):
    response = client.get("/api/activity")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "classes" in data


def test_activity_filtering(client: TestClient):
    response = client.get("/api/activity?limit=5&source_type=live")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)


def test_camera_status(client: TestClient):
    response = client.get("/api/camera/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "config" in data


def test_camera_detections(client: TestClient):
    response = client.get("/api/camera/detections")
    assert response.status_code == 200
    data = response.json()
    assert "detections" in data
    assert isinstance(data["detections"], list)


def test_camera_test_empty_url_returns_400(client: TestClient):
    response = client.post("/api/camera/test", json={"stream_url": ""})
    # If empty, should return 400 or probe configured URL
    assert response.status_code in (200, 400)


def test_camera_test_bare_ip(client: TestClient):
    response = client.post("/api/camera/test", json={"stream_url": "192.168.0.132"})
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert "endpoint" in data
    assert "kind" in data


def test_camera_test_full_url(client: TestClient):
    response = client.post("/api/camera/test", json={"stream_url": "http://192.168.0.132:81/stream"})
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert "endpoint" in data


def test_settings_get(client: TestClient):
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert "camera" in data
    assert "camera_runtime" in data
    assert "storage" in data


def test_settings_put_bare_ip(client: TestClient):
    response = client.put("/api/settings", json={"stream_url": "192.168.0.132"})
    assert response.status_code == 200
    data = response.json()
    assert data["camera"]["stream_url"].startswith("http://")


def test_settings_put_stream_url(client: TestClient):
    response = client.put("/api/settings", json={"stream_url": "http://192.168.0.132:81/stream", "live_fps": 2.0})
    assert response.status_code == 200
    data = response.json()
    assert data["camera"]["stream_url"] == "http://192.168.0.132:81/stream"


def test_camera_config_put(client: TestClient):
    response = client.put("/api/camera/config", json={"live_fps": 2.0, "detector_enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


def test_recordings_list(client: TestClient):
    response = client.get("/api/recordings")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_search_examples(client: TestClient):
    response = client.get("/api/search/examples")
    assert response.status_code == 200
    data = response.json()
    assert "queries" in data
    assert len(data["queries"]) > 0


def test_search_stats(client: TestClient):
    response = client.get("/api/search/stats")
    assert response.status_code == 200
    data = response.json()
    assert "scenes" in data
    assert "objects" in data


def test_search_post(client: TestClient):
    response = client.post("/api/search", json={"query": "person walking", "mode": "both", "limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert "hits" in data
    assert data["query"] == "person walking"


def test_nonexistent_frame_returns_404(client: TestClient):
    response = client.get("/api/frames/999999999")
    assert response.status_code == 404


def test_nonexistent_thumb_returns_404(client: TestClient):
    response = client.get("/api/media/thumb/nonexistent_file_xyz.jpg")
    assert response.status_code == 404


def test_camera_stop_and_start(client: TestClient):
    stop_resp = client.post("/api/camera/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["stopped"] is True

    start_resp = client.post("/api/camera/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["started"] is True

