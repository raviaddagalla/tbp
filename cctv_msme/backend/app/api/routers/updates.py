"""Admin endpoints: signed update bundle verification (Phase 4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import require_roles
from app.db.models import User
from app.services.updates.verify import list_entries, verify_bundle

router = APIRouter(tags=["admin"])


@router.post("/admin/updates/verify")
async def verify_update_bundle(
    bundle: UploadFile = File(...),
    signature: str = Form(...),
    user: User = Depends(require_roles("admin")),
):
    data = await bundle.read()
    ok, detail = verify_bundle(data, signature)
    return {
        "filename": bundle.filename,
        "verified": ok,
        "detail": detail,
        "entries": list_entries(data) if ok else [],
        "size_bytes": len(data),
    }
