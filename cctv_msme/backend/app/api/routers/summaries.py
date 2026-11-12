"""Shift summaries + export."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import ensure_zone_access, require_roles, require_zone_scope
from app.db.base import get_db
from app.db.models import Summary, User
from app.schemas import SummaryOut, SummaryRequest
from app.services.summaries.service import (
    generate_shift_summary,
    render_html,
    render_txt,
)
from app.state import state

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.post("", response_model=SummaryOut)
async def create_summary(
    body: SummaryRequest,
    user: User = Depends(require_roles("supervisor", "admin")),
):
    zone = user.zone or "General"
    summary = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_shift_summary(
            body.hours, body.title, user.username, zone, state.llm, state.embedder, state.vector_store
        ),
    )
    return summary


@router.get("", response_model=list[SummaryOut])
def list_summaries(user: User = Depends(require_roles("supervisor", "admin")), db: Session = Depends(get_db)):
    zones = require_zone_scope(user, None)
    q = db.query(Summary)
    if zones:
        q = q.filter(Summary.zone.in_(zones))
    return q.order_by(Summary.id.desc()).limit(50).all()


def _get_scoped_summary(summary_id: int, user: User, db: Session) -> Summary:
    summary = db.get(Summary, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    ensure_zone_access(user, summary.zone)
    return summary


@router.get("/{summary_id}", response_model=SummaryOut)
def get_summary(
    summary_id: int,
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    return _get_scoped_summary(summary_id, user, db)


@router.get("/{summary_id}/export")
def export_summary(
    summary_id: int,
    format: str = "txt",
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    summary = _get_scoped_summary(summary_id, user, db)
    if format == "html":
        return Response(
            content=render_html(summary),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="summary_{summary.id}.html"'},
        )
    return Response(
        content=render_txt(summary),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="summary_{summary.id}.txt"'},
    )
