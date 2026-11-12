"""Anomaly detector behavior: prompt scoring and the per-camera cooldown."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pytest


class _Hub:
    class _Lock:
        _loop = None

    _lock = _Lock()

    async def broadcast(self, *args, **kwargs):
        pass


class _Camera:
    id = 1
    name = "CAM01"
    zone = "Logistics"
    anomaly_enabled = True


def _emb(text: str, dim: int = 64) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    for i, ch in enumerate(text):
        v[i % dim] += ord(ch)
    v += 0.01
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n else v


class _FakeEmbedder:
    def embed_texts(self, texts):
        return np.stack([_emb(t) for t in texts])


@pytest.fixture
def detector(monkeypatch):
    from app.services.alerts.anomaly import AnomalyDetector

    monkeypatch.setattr("app.services.alerts.anomaly.get_settings", lambda: _settings(threshold=0.05, cooldown=60))
    det = AnomalyDetector(_FakeEmbedder(), _Hub())
    return det


def _settings(threshold: float, cooldown: int):
    class S:
        anomaly_threshold = threshold
        anomaly_cooldown_seconds = cooldown

    return S()


def _camera():
    return _Camera()


def _frame():
    return np.zeros((8, 8, 3), dtype=np.uint8)


def test_score_frame_flags_fire(monkeypatch):
    from app.services.alerts.anomaly import AnomalyDetector

    monkeypatch.setattr("app.services.alerts.anomaly.get_settings", lambda: _settings(threshold=0.0, cooldown=60))
    det = AnomalyDetector(_FakeEmbedder(), _Hub())
    # A frame embedding identical to the "no_helmet" prompt should fire
    emb = _emb("a person working without a safety helmet")
    alert_type, score = det.score_frame(emb)
    assert alert_type == "no_helmet"
    assert score >= 0.0


def test_cooldown_suppresses_repeat_alerts(monkeypatch, detector):
    """Two detections within the cooldown window must produce exactly one alert."""
    from app.services.alerts.anomaly import get_settings as _gs
    from app.services.alerts.tracking import track_movement
    from app.services.db_support import save_alert

    calls = {"alerts": 0}

    def fake_save_alert(**kwargs):
        calls["alerts"] += 1
        return _Alert(**kwargs)

    def fake_track(*args, **kwargs):
        return []

    monkeypatch.setattr("app.services.alerts.anomaly.save_alert", fake_save_alert)
    monkeypatch.setattr("app.services.alerts.anomaly.track_movement", fake_track)
    monkeypatch.setattr("app.services.alerts.anomaly._commit_alert", lambda a: None)

    ts = datetime.now(timezone.utc)
    cam = _Camera()
    detector(cam, _frame(), ts, _emb("a person working without a safety helmet"), "thumbs/1_1_1.jpg", "seg", 0.0)
    detector(cam, _frame(), ts, _emb("a person working without a safety helmet"), "thumbs/1_1_2.jpg", "seg", 0.5)
    assert calls["alerts"] == 1, "cooldown must suppress the second alert"

    # After the cooldown window expires, a new detection fires again
    detector._last_alert[cam.id] = time.time() - detector.cooldown - 1
    detector(cam, _frame(), ts, _emb("a person working without a safety helmet"), "thumbs/1_1_3.jpg", "seg", 1.0)
    assert calls["alerts"] == 2, "alert must fire again after cooldown expires"


def test_cooldown_is_per_camera(monkeypatch, detector):
    from app.services.alerts.anomaly import get_settings as _gs

    calls = {"alerts": 0}

    def fake_save_alert(**kwargs):
        calls["alerts"] += 1
        return _Alert(**kwargs)

    monkeypatch.setattr("app.services.alerts.anomaly.save_alert", fake_save_alert)
    monkeypatch.setattr("app.services.alerts.anomaly.track_movement", lambda *a, **k: [])
    monkeypatch.setattr("app.services.alerts.anomaly._commit_alert", lambda a: None)

    ts = datetime.now(timezone.utc)
    cam1 = _Camera()
    cam2 = _Camera()
    cam2.id = 2
    detector(cam1, _frame(), ts, _emb("a person working without a safety helmet"), "thumbs/1_1_1.jpg", "s", 0.0)
    detector(cam2, _frame(), ts, _emb("a person working without a safety helmet"), "thumbs/2_1_1.jpg", "s", 0.0)
    # Both fire: cooldown is keyed per camera id
    assert calls["alerts"] == 2


class _Alert:
    def __init__(self, **kwargs):
        self.id = 1
        self.trail_json = {}
