"""SQLAlchemy models: one ESP32 camera, uploaded recordings, frames, detections."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CameraConfig(Base):
    """The single ESP32-CAM configuration plus its persisted runtime status."""

    __tablename__ = "camera_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    stream_url: Mapped[str] = mapped_column(Text, default="http://192.168.0.132:81/stream")
    live_fps: Mapped[float] = mapped_column(Float, default=2.0)
    index_interval_seconds: Mapped[float] = mapped_column(Float, default=3.0)
    detector_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_start: Mapped[bool] = mapped_column(Boolean, default=True)
    default_sample_fps: Mapped[float] = mapped_column(Float, default=2.0)

    # Runtime status (written by the camera thread, read by the API)
    status: Mapped[str] = mapped_column(String(16), default="offline")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    frames_received: Mapped[int] = mapped_column(Integer, default=0)
    frames_indexed: Mapped[int] = mapped_column(Integer, default=0)
    objects_detected: Mapped[int] = mapped_column(Integer, default=0)
    frame_width: Mapped[int] = mapped_column(Integer, default=0)
    frame_height: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Recording(Base):
    """An uploaded video file being indexed (or fully indexed)."""

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    original_name: Mapped[str] = mapped_column(String(256), default="")
    stored_name: Mapped[str] = mapped_column(String(128), default="")
    path: Mapped[str] = mapped_column(Text, default="")
    # queued | processing | ready | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)
    sample_fps: Mapped[float] = mapped_column(Float, default=2.0)
    frames_indexed: Mapped[int] = mapped_column(Integer, default=0)
    frames_planned: Mapped[int] = mapped_column(Integer, default=0)
    objects_detected: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    frames: Mapped[list["Frame"]] = relationship(back_populates="recording", cascade="all, delete-orphan")


class Frame(Base):
    """One sampled video frame, from an upload or the live camera."""

    __tablename__ = "frames"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(8), default="upload")  # upload | live
    recording_id: Mapped[int | None] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), nullable=True)
    frame_number: Mapped[int] = mapped_column(Integer, default=0)
    # Seconds into the source video (0 for live snapshots).
    timestamp_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    scene_vector_id: Mapped[str] = mapped_column(String(64), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    objects_count: Mapped[int] = mapped_column(Integer, default=0)

    recording: Mapped[Recording | None] = relationship(back_populates="frames")
    detections: Mapped[list["Detection"]] = relationship(back_populates="frame", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_frames_source_captured", "source_type", "captured_at"),
        Index("ix_frames_recording_ts", "recording_id", "timestamp_seconds"),
    )


class Detection(Base):
    """A tracked object detection inside a sampled frame."""

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    recording_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(8), default="upload")
    track_id: Mapped[int] = mapped_column(Integer, default=0)
    object_class: Mapped[str] = mapped_column(String(32), default="object", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Normalised (0-1) box corners, resolution independent.
    x1: Mapped[float] = mapped_column(Float, default=0.0)
    y1: Mapped[float] = mapped_column(Float, default=0.0)
    x2: Mapped[float] = mapped_column(Float, default=0.0)
    y2: Mapped[float] = mapped_column(Float, default=0.0)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    object_vector_id: Mapped[str] = mapped_column(String(64), default="")
    attributes: Mapped[str] = mapped_column(String(64), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    timestamp_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    frame: Mapped[Frame] = relationship(back_populates="detections")

    __table_args__ = (
        Index("ix_detections_class_time", "object_class", "captured_at"),
        Index("ix_detections_track", "source_type", "track_id"),
    )


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    recording_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
