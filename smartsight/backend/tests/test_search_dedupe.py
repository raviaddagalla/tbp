"""Search ranking helpers: timeline keys and near-duplicate suppression."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.search import SCENE_DEDUPE_SECONDS, _dedupe, _scene_key, _timeline


def make_hit(seconds: float, score: float, *, source_type: str = "upload", frame_id: int | None = None):
    return SimpleNamespace(
        id=f"vec-{seconds}-{score}",
        score=score,
        metadata={
            "source_type": source_type,
            "recording_id": 1,
            "timestamp_seconds": seconds,
            # Upload frames are indexed seconds apart in wall-clock time.
            "ts_epoch": 1_000_000 + seconds * 9,
            "frame_id": frame_id if frame_id is not None else int(seconds * 10),
        },
    )


def test_upload_timeline_uses_footage_position():
    assert _timeline(make_hit(12.5, 0.2)) == 12.5


def test_live_timeline_uses_capture_time():
    hit = make_hit(0.0, 0.2, source_type="live")
    assert _timeline(hit) == hit.metadata["ts_epoch"]


def test_dedupe_keeps_one_hit_per_aligned_window():
    hits = [make_hit(second, 0.2 + second / 100) for second in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)]
    kept = _dedupe(hits, _scene_key, SCENE_DEDUPE_SECONDS)
    assert len(kept) == 1
    assert _timeline(kept[0]) == 3.5  # highest score inside the 0-4s window


def test_dedupe_keeps_one_hit_per_window_across_a_clip():
    hits = [make_hit(second, 0.1) for second in range(0, 24, 2)]
    kept = _dedupe(hits, _scene_key, 4.0)
    assert sorted(_timeline(hit) for hit in kept) == [0.0, 4.0, 8.0, 12.0, 16.0, 20.0]


def test_dedupe_does_not_mix_recordings():
    first = make_hit(10.0, 0.3)
    second = make_hit(10.0, 0.25)
    second.metadata["recording_id"] = 2
    kept = _dedupe([first, second], _scene_key, 4.0)
    assert len(kept) == 2
