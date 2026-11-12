"""SQLAlchemy ORM models (SQLite for MVP, Postgres-ready)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(256))
    # worker | supervisor | admin
    role: Mapped[str] = mapped_column(String(16), default="worker")
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    rtsp_url: Mapped[str] = mapped_column(Text)
    zone: Mapped[str] = mapped_column(String(64), default="General")
    location_label: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sample_interval_seconds: Mapped[float] = mapped_column(Float, default=0.5)
    retention_hours: Mapped[int] = mapped_column(Integer, default=72)
    clip_segment_seconds: Mapped[int] = mapped_column(Integer, default=30)
    anomaly_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    detector_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reid_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Phase 2: per-camera ReID
    batch_reprocess_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Phase 3
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Runtime health (kept on the row for cheap status reads)
    status: Mapped[str] = mapped_column(String(16), default="offline")  # online|offline|reconnecting
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    frames_indexed: Mapped[int] = mapped_column(Integer, default=0)
    alerts_count: Mapped[int] = mapped_column(Integer, default=0)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(256))
    storage_path: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(16), default="pdf")  # pdf|docx|image|text
    zone: Mapped[str] = mapped_column(String(64), default="General")
    # pending | processing | processed | failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SearchLog(Base):
    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    query: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="video")  # video|doc|chat
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    camera_name: Mapped[str] = mapped_column(String(128), default="")
    zone: Mapped[str] = mapped_column(String(64), default="")
    alert_type: Mapped[str] = mapped_column(String(64))  # e.g. no_helmet|smoke|restricted_zone|spill
    description: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    thumbnail_path: Mapped[str] = mapped_column(Text, default="")
    segment_id: Mapped[str] = mapped_column(String(64), default="")
    clip_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    # open | acknowledged
    status: Mapped[str] = mapped_column(String(16), default="open")
    trail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[str] = mapped_column(Text, default="")
    acknowledged_by: Mapped[str] = mapped_column(String(64), default="")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16), default="shift")  # shift|incident
    zone: Mapped[str] = mapped_column(String(64), default="General")
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    tags_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # camera|document|alert|search|summary|system
    message: Mapped[str] = mapped_column(Text)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Tracklet(Base):
    """Intra-camera tracklet: a stable per-camera object identity across
    sampled frames, with aggregated embeddings for cross-camera stitching."""

    __tablename__ = "tracklets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    local_track_id: Mapped[int] = mapped_column(Integer, index=True)
    object_class: Mapped[str] = mapped_column(String(32), default="person")
    start_ts: Mapped[datetime] = mapped_column(DateTime)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    # aggregated CLIP embeddings (mean + centroid of the per-frame crops)
    mean_embedding: Mapped[str] = mapped_column(Text, default="")  # base64 float32 npy
    # aggregated ReID embedding (Phase 2) for cross-camera identity
    reid_embedding: Mapped[str] = mapped_column(Text, default="")
    attrs_json: Mapped[dict] = mapped_column(JSON, default=dict)  # attr_color, attr_type, ...
    last_ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CameraAdjacency(Base):
    """Floor-plan graph edge: cameras that share a sight line, with the
    expected transit-time window between them (manual calibration)."""

    __tablename__ = "camera_adjacency"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    to_camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    expected_transit_seconds_min: Mapped[int] = mapped_column(Integer, default=5)
    expected_transit_seconds_max: Mapped[int] = mapped_column(Integer, default=300)
    direction_label: Mapped[str] = mapped_column(String(128), default="")
    # floor-plan pin coordinates (percentages) for the calibration UI
    from_x: Mapped[float] = mapped_column(Float, default=0.0)
    from_y: Mapped[float] = mapped_column(Float, default=0.0)
    to_x: Mapped[float] = mapped_column(Float, default=0.0)
    to_y: Mapped[float] = mapped_column(Float, default=0.0)
    floorplan_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FloorPlan(Base):
    """Uploaded floor-plan image with per-camera pin positions (percentages)."""

    __tablename__ = "floor_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="Site Floor Plan")
    image_path: Mapped[str] = mapped_column(Text, default="")
    pins_json: Mapped[dict] = mapped_column(JSON, default=dict)  # camera_id -> {x, y}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
