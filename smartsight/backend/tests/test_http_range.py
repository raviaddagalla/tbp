"""HTTP Range support used by <video> seeking in search results."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.http_range import range_file_response


@pytest.fixture()
def client(tmp_path: Path):
    payload = bytes(range(256)) * 40  # 10 240 bytes
    video = tmp_path / "clip.mp4"
    video.write_bytes(payload)

    app = FastAPI()

    @app.get("/video")
    def video_endpoint(request: Request):
        return range_file_response(video, request, media_type="video/mp4", filename="clip.mp4")

    with TestClient(app) as test_client:
        test_client.payload = payload  # type: ignore[attr-defined]
        yield test_client


def test_full_request_advertises_range_support(client):
    response = client.get("/video")
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == client.payload
    assert response.headers["content-type"] == "video/mp4"


def test_middle_range_returns_only_requested_bytes(client):
    response = client.get("/video", headers={"Range": "bytes=1000-1999"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(client.payload)}"
    assert len(response.content) == 1000
    assert response.content == client.payload[1000:2000]


def test_open_ended_range_reads_to_end(client):
    response = client.get("/video", headers={"Range": f"bytes={len(client.payload) - 10}-"})
    assert response.status_code == 206
    assert response.content == client.payload[-10:]


def test_suffix_range_reads_last_bytes(client):
    response = client.get("/video", headers={"Range": "bytes=-64"})
    assert response.status_code == 206
    assert response.content == client.payload[-64:]
    assert response.headers["content-range"] == f"bytes {len(client.payload) - 64}-{len(client.payload) - 1}/{len(client.payload)}"


def test_range_beyond_file_is_rejected(client):
    response = client.get("/video", headers={"Range": f"bytes={len(client.payload) + 10}-{len(client.payload) + 20}"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(client.payload)}"
