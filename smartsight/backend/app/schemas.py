"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CameraConfigUpdate(BaseModel):
    stream_url: str | None = Field(default=None, max_length=500)
    live_fps: float | None = Field(default=None, ge=0.5, le=10)
    index_interval_seconds: float | None = Field(default=None, ge=1, le=120)
    detector_enabled: bool | None = None
    auto_start: bool | None = None
    default_sample_fps: float | None = Field(default=None, ge=0.5, le=10)


class ProbeRequest(BaseModel):
    stream_url: str | None = Field(default=None, max_length=500)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    mode: Literal["both", "scene", "object"] = "both"
    limit: int = Field(default=12, ge=1, le=50)
    source_type: Literal["live", "upload"] | None = None
    recording_id: int | None = None
    object_class: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
