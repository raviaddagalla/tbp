"""Pydantic schemas shared across API routers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    full_name: str = ""
    email: str = ""
    role: Literal["worker", "supervisor", "admin"] = "worker"
    zone: str | None = None


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str
    email: str
    role: str
    zone: str | None
    is_active: bool
    created_at: datetime


# ---------- Cameras ----------
class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    zone: str = "General"
    location_label: str = ""
    is_active: bool = True
    sample_interval_seconds: float | None = Field(default=None, ge=0.1, le=600)
    retention_hours: int = Field(default=72, ge=1, le=8760)
    clip_segment_seconds: int = Field(default=30, ge=10, le=300)
    anomaly_enabled: bool = False
    detector_enabled: bool | None = None
    reid_enabled: bool | None = None
    batch_reprocess_enabled: bool | None = None


class CameraUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    zone: str | None = None
    location_label: str | None = None
    is_active: bool | None = None
    sample_interval_seconds: float | None = Field(default=None, ge=0.1, le=600)
    retention_hours: int | None = Field(default=None, ge=1, le=8760)
    clip_segment_seconds: int | None = Field(default=None, ge=10, le=300)
    anomaly_enabled: bool | None = None
    detector_enabled: bool | None = None
    reid_enabled: bool | None = None
    batch_reprocess_enabled: bool | None = None


class CameraOut(ORMModel):
    id: int
    name: str
    rtsp_url: str
    zone: str
    location_label: str
    is_active: bool
    sample_interval_seconds: float
    retention_hours: int
    clip_segment_seconds: int
    anomaly_enabled: bool
    detector_enabled: bool
    reid_enabled: bool
    batch_reprocess_enabled: bool
    status: str
    last_seen_at: datetime | None
    connected_at: datetime | None
    last_error: str
    frames_processed: int
    frames_indexed: int
    alerts_count: int
    created_at: datetime


class CameraHealthOut(BaseModel):
    camera_id: int
    status: str
    frames_indexed: int
    frames_processed: int = 0
    last_seen_at: datetime | None
    # Upload / file:// footage progress (seconds of footage, 0 for live cams)
    file_duration_seconds: float = 0.0
    file_indexed_seconds: float = 0.0


# ---------- Documents ----------
class DocumentOut(ORMModel):
    id: int
    filename: str
    doc_type: str
    zone: str
    status: str
    error: str
    pages: int
    chunk_count: int
    ocr_used: bool
    uploaded_by: int
    created_at: datetime


# ---------- Search ----------
class VideoSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    camera_ids: list[int] | None = None
    zones: list[str] | None = None
    start: datetime | None = None
    end: datetime | None = None
    top_k: int = Field(default=12, ge=1, le=50)


class VideoSearchHit(BaseModel):
    id: str
    camera_id: int
    camera_name: str
    zone: str
    timestamp: datetime
    score: float
    thumbnail_url: str
    clip_url: str
    clip_offset_seconds: float
    explanation: str


class VideoSearchResponse(BaseModel):
    query: str
    hits: list[VideoSearchHit]
    total: int
    search_id: int


# ---------- Entity (object) search — Phase 1 ----------
class EntitySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    camera_ids: list[int] | None = None
    zones: list[str] | None = None
    start: datetime | None = None
    end: datetime | None = None
    object_class: str | None = None
    top_k: int = Field(default=16, ge=1, le=50)


class EntitySearchHit(BaseModel):
    id: str
    camera_id: int
    camera_name: str
    zone: str
    timestamp: datetime
    score: float
    object_class: str
    bbox: str
    detection_confidence: float
    tracklet_local_id: int
    thumbnail_url: str
    frame_thumbnail_url: str
    clip_url: str
    clip_offset_seconds: float
    attrs: dict[str, str]


class EntitySearchResponse(BaseModel):
    query: str
    object_class: str | None
    hits: list[EntitySearchHit]
    total: int
    search_id: int


class DocumentSearchHit(BaseModel):
    id: str
    document_id: int
    filename: str
    page: int
    section: str
    zone: str = ""
    chunk_text: str
    score: float


# ---------- Temporal (Phase 3) ----------
class TemporalSearchHit(VideoSearchHit):
    window_start: datetime | None = None
    window_end: datetime | None = None
    frame_count: int = 0


class TemporalSearchResponse(BaseModel):
    query: str
    hits: list[TemporalSearchHit]
    total: int
    temporal_used: bool
    search_id: int


# ---------- Chat / RAG ----------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    include_video: bool = True


class Citation(BaseModel):
    document_id: int
    filename: str
    page: int
    section: str
    score: float


class VideoEvidence(BaseModel):
    camera_name: str
    zone: str
    timestamp: datetime
    score: float
    thumbnail_url: str
    clip_url: str
    clip_offset_seconds: float


class ChatResponse(BaseModel):
    answer: str
    language: str
    citations: list[Citation]
    video_evidence: list[VideoEvidence]
    intent: dict[str, bool]
    provider: str


# ---------- Summaries ----------
class SummaryRequest(BaseModel):
    hours: int = Field(default=8, ge=1, le=168)
    title: str | None = None


class SummaryOut(ORMModel):
    id: int
    title: str
    kind: str
    zone: str
    content: str
    created_by: str
    window_start: datetime
    window_end: datetime
    tags_json: dict
    created_at: datetime


# ---------- Alerts ----------
class AlertOut(ORMModel):
    id: int
    camera_id: int
    camera_name: str
    zone: str
    alert_type: str
    description: str
    score: float
    timestamp: datetime
    thumbnail_url: str
    clip_url: str | None
    clip_offset_seconds: float
    status: str
    trail: list[dict]
    report: str
    acknowledged_by: str
    acknowledged_at: datetime | None


class AlertReportRequest(BaseModel):
    generate_report: bool = True


# ---------- Analytics ----------
class AnalyticsOverview(BaseModel):
    cameras_total: int
    cameras_online: int
    frames_indexed: int
    documents_total: int
    documents_processed: int
    chunks_indexed: int
    searches_total: int
    searches_last_7d: int
    alerts_open: int
    top_zones: list[dict[str, Any]]
    searches_by_day: list[dict[str, Any]]
    document_usage: list[dict[str, Any]]
    activity: list[dict[str, Any]]


class LoadStatus(BaseModel):
    active_cameras: int
    effective_sample_interval: float
    llm_provider: str
    llm_model: str
    embedding_device: str
    vector_store_backend: str
    queue_depth: int


class CameraDiagnostics(BaseModel):
    id: int
    name: str
    zone: str
    status: str
    last_seen_at: datetime | None = None
    connected_at: datetime | None = None
    last_error: str = ""
    frames_processed: int = 0
    frames_indexed: int = 0
    alerts_count: int = 0
    inflight: int = 0
    sample_interval_seconds: float = 0.5
    retention_hours: int = 72
    detector_enabled: bool = False
    reid_enabled: bool = False
    batch_reprocess_enabled: bool = False
    anomaly_enabled: bool = False
    object_vectors: int = 0
    clip_event_vectors: int = 0


class SystemDiagnostics(BaseModel):
    vector_store_backend: str
    queue_depth: int
    effective_sample_interval: float
    llm_provider: str
    llm_model: str
    embedding_device: str
    reid_model: str
    data_dir: str
    retention_hours: int
    cameras: list[CameraDiagnostics]


# ---------- Misc ----------
class MessageResponse(BaseModel):
    message: str


class WebSocketEvent(BaseModel):
    type: str
    payload: dict[str, Any] = {}


class ActionAck(BaseModel):
    ok: bool = True
    detail: str = ""
