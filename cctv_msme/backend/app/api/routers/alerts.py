"""Safety alerts: feed, acknowledge, timeline, incident reports."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import ensure_zone_access, require_roles, require_zone_scope
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Alert, Camera, User
from app.schemas import AlertOut, AlertReportRequest
from app.services.rag import prompts
from app.state import state

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _to_out(alert: Alert) -> AlertOut:
    cam_id = alert.camera_id
    seg = alert.segment_id
    clip_url = f"/api/streams/clip/{cam_id}/{seg}.mp4" if seg else None
    return AlertOut(
        id=alert.id,
        camera_id=cam_id,
        camera_name=alert.camera_name,
        zone=alert.zone,
        alert_type=alert.alert_type,
        description=alert.description,
        score=alert.score,
        timestamp=alert.timestamp,
        thumbnail_url=f"/api/streams/thumb/{alert.thumbnail_path}",
        clip_url=clip_url,
        clip_offset_seconds=alert.clip_offset_seconds,
        status=alert.status,
        trail=alert.trail_json.get("steps", []) if alert.trail_json else [],
        report=alert.report,
        acknowledged_by=alert.acknowledged_by,
        acknowledged_at=alert.acknowledged_at,
    )


@router.get("", response_model=list[AlertOut])
def list_alerts(
    status: str | None = None,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    zones = require_zone_scope(user, None)
    q = db.query(Alert)
    if zones:
        q = q.filter(Alert.zone.in_(zones))
    if status:
        q = q.filter(Alert.status == status)
    q = q.order_by(Alert.id.desc()).limit(200)
    return [_to_out(a) for a in q.all()]


def _get_scoped_alert(alert_id: int, user: User, db: Session) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    ensure_zone_access(user, alert.zone)
    return alert


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    alert = _get_scoped_alert(alert_id, user, db)
    alert.status = "acknowledged"
    alert.acknowledged_by = user.username
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return _to_out(alert)


@router.post("/{alert_id}/dismiss", response_model=AlertOut)
def dismiss_alert(
    alert_id: int,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    """Mark a false positive / resolved alert as dismissed so it leaves the open queue."""
    alert = _get_scoped_alert(alert_id, user, db)
    alert.status = "dismissed"
    alert.acknowledged_by = user.username
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return _to_out(alert)


@router.get("/{alert_id}/timeline")
def alert_timeline(
    alert_id: int,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    """Clips before/during/after the alert from the rolling segment store."""
    alert = _get_scoped_alert(alert_id, user, db)
    settings = get_settings()
    camera_dir = settings.clips_dir / str(alert.camera_id)
    epoch = alert.timestamp.timestamp()
    window = timedelta(seconds=180)
    clips = []
    if camera_dir.exists():
        for f in sorted(camera_dir.glob("*.mp4")):
            try:
                seg_epoch = int(f.stem.split("_")[-1])
            except ValueError:
                continue
            if abs(seg_epoch - epoch) <= window.total_seconds():
                clips.append(
                    {
                        "segment_id": f.stem,
                        "start": seg_epoch,
                        "clip_url": f"/api/streams/clip/{alert.camera_id}/{f.name}",
                    }
                )
    clips.sort(key=lambda c: c["start"])
    return {
        "alert_id": alert_id,
        "camera_id": alert.camera_id,
        "clips": clips,
    }


@router.post("/{alert_id}/report", response_model=AlertOut)
async def generate_report(
    alert_id: int,
    body: AlertReportRequest,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    alert = _get_scoped_alert(alert_id, user, db)
    timeline = await alert_timeline(alert_id, user, db)
    alert_dict = {
        "alert_type": alert.alert_type,
        "camera_name": alert.camera_name,
        "zone": alert.zone,
        "timestamp": alert.timestamp,
        "score": alert.score,
        "description": alert.description,
    }
    user_prompt = prompts.build_incident_user(alert_dict, timeline.get("clips", []))
    try:
        report = await asyncio.get_event_loop().run_in_executor(
            None, lambda: state.llm.chat(prompts.INCIDENT_SYSTEM, user_prompt)
        )
    except Exception:  # noqa: BLE001
        from app.services.rag.llm.mock import MockLLM

        report = MockLLM().chat(prompts.INCIDENT_SYSTEM, user_prompt)
    alert.report = report
    db.commit()
    db.refresh(alert)
    return _to_out(alert)


@router.post("/{alert_id}/export")
def export_alert_report(
    alert_id: int,
    format: str = "txt",
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    alert = _get_scoped_alert(alert_id, user, db)
    from fastapi import Response

    text = (
        f"INCIDENT REPORT - {alert.alert_type.upper()}\n"
        f"Location: {alert.camera_name} ({alert.zone})\n"
        f"Timestamp: {alert.timestamp} UTC | Similarity: {alert.score}\n\n"
        f"Description: {alert.description}\n\n"
        f"Detailed report:\n{alert.report or '(no report generated yet - use Generate Report)'}\n"
    )
    if format == "html":
        body = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
        html = f"<html><body style='font-family:Arial;margin:40px'><h2>Incident Report</h2>{body}</body></html>"
        return Response(content=html, media_type="text/html", headers={"Content-Disposition": "attachment; filename=incident.html"})
    return Response(content=text, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": "attachment; filename=incident.txt"})
