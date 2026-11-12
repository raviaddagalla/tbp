"""Recording probing and validation helpers."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.services.indexing.recordings import ALLOWED_EXTENSIONS, probe_video


def _write_video(path: Path, frames: int = 30, fps: float = 15.0, size=(160, 120)) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    assert writer.isOpened(), "OpenCV could not create a test video"
    for index in range(frames):
        frame = np.full((size[1], size[0], 3), 40 + index, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_probe_video_reads_metadata(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    _write_video(video)
    info = probe_video(video)
    assert info.ok
    assert info.width == 160
    assert info.height == 120
    assert info.fps == 15.0
    assert info.total_frames == 30
    assert info.duration_seconds == 2.0


def test_probe_video_rejects_missing_file(tmp_path: Path):
    info = probe_video(tmp_path / "missing.mp4")
    assert not info.ok
    assert "not found" in info.error.lower()


def test_probe_video_rejects_non_video(tmp_path: Path):
    fake = tmp_path / "notes.mp4"
    fake.write_text("this is not a video at all")
    info = probe_video(fake)
    assert not info.ok


def test_supported_upload_extensions_cover_the_documented_formats():
    assert {"mp4", "mov", "avi", "mkv", "webm"}.issubset(ALLOWED_EXTENSIONS)
