"""Shared small utilities (time, JPEG, text)."""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; interpret those as UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def to_iso(value: datetime | None) -> str:
    normalised = as_utc(value)
    return normalised.isoformat() if normalised else ""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
