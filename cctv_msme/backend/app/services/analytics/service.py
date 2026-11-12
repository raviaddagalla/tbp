"""Analytics service: dashboard numbers, search stats, document usage."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.db.base import SessionLocal
from app.db.models import Alert, Camera, Document, SearchLog

logger = logging.getLogger(__name__)


def overview() -> dict:
    db = SessionLocal()
    try:
        cameras = db.query(Camera).all()
        cameras_total = len(cameras)
        cameras_online = sum(1 for c in cameras if c.status == "online")
        frames_indexed = sum(c.frames_indexed or 0 for c in cameras)

        docs = db.query(Document).all()
        documents_total = len(docs)
        documents_processed = sum(1 for d in docs if d.status == "processed")

        searches_total = db.query(func.count(SearchLog.id)).scalar() or 0
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        searches_last_7d = (
            db.query(func.count(SearchLog.id)).filter(SearchLog.created_at >= week_ago).scalar() or 0
        )
        alerts_open = db.query(func.count(Alert.id)).filter(Alert.status == "open").scalar() or 0

        # Top searched zones (parse filters_json)
        rows = db.query(SearchLog.filters_json).filter(SearchLog.kind == "video").all()
        zone_counts: dict[str, int] = {}
        for (fj,) in rows:
            zones = (fj or {}).get("zones") or []
            if isinstance(zones, list):
                for z in zones:
                    zone_counts[z] = zone_counts.get(z, 0) + 1
        top_zones = [{"zone": k, "count": v} for k, v in sorted(zone_counts.items(), key=lambda kv: -kv[1])[:6]]

        # Searches per day (last 7 days)
        day_counts: dict[str, int] = {}
        for i in range(6, -1, -1):
            day_counts[(datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")] = 0
        recent = (
            db.query(func.date(SearchLog.created_at), func.count(SearchLog.id))
            .filter(SearchLog.created_at >= week_ago)
            .group_by(func.date(SearchLog.created_at))
            .all()
        )
        for d, c in recent:
            if d:
                day_counts[d] = c
        searches_by_day = [{"date": k, "count": v} for k, v in day_counts.items()]

        # Document usage: counts of docs with chunks (via vector store) — approximate via chunk counts
        document_usage = [
            {"filename": d.filename, "chunks": d.chunk_count, "status": d.status, "pages": d.pages}
            for d in docs
        ]
        document_usage.sort(key=lambda x: -x["chunks"])

        activity = _recent_activity(db)
    finally:
        db.close()

    return {
        "cameras_total": cameras_total,
        "cameras_online": cameras_online,
        "frames_indexed": frames_indexed,
        "documents_total": documents_total,
        "documents_processed": documents_processed,
        "chunks_indexed": sum(d["chunks"] for d in document_usage),
        "searches_total": searches_total,
        "searches_last_7d": searches_last_7d,
        "alerts_open": alerts_open,
        "top_zones": top_zones,
        "searches_by_day": searches_by_day,
        "document_usage": document_usage,
        "activity": activity,
    }


def _recent_activity(db, limit: int = 12) -> list[dict]:
    from app.db.models import ActivityEvent

    rows = (
        db.query(ActivityEvent)
        .order_by(ActivityEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "kind": r.kind,
            "message": r.message,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def log_search(user_id: int, username: str, query: str, kind: str, filters: dict, results_count: int) -> int:
    db = SessionLocal()
    try:
        log = SearchLog(
            user_id=user_id,
            username=username,
            query=query[:500],
            kind=kind,
            filters_json=filters,
            results_count=results_count,
        )
        db.add(log)
        db.commit()
        return log.id
    finally:
        db.close()
