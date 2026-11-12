"""Document upload + library management."""
from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.api.deps import ensure_zone_access, get_current_user, require_roles, require_zone_scope
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Document, User
from app.schemas import DocumentOut, MessageResponse
from app.services.activity_feed import record as record_activity
from app.services.documents.ingester import run_ingestion
from app.state import state

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".txt": "text",
    ".md": "text",
}

MAX_UPLOAD_MB = 40


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    zone: str = Form("General"),
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED)}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_MB} MB limit")

    settings = get_settings()
    doc_id = uuid.uuid4().hex[:12]
    dest_dir = settings.uploads_dir / doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"doc_{doc_id}{ext}").name
    dest = dest_dir / safe_name
    dest.write_bytes(content)

    # Mirror to the shared bucket (best-effort) so other laptops can ingest.
    try:
        from app.services.media_storage import media_put

        media_put(f"uploads/{doc_id}/{safe_name}", content)
    except Exception:  # noqa: BLE001
        pass

    doc = Document(
        filename=safe_name,
        storage_path=str(dest),
        doc_type=ALLOWED[ext],
        zone=zone.strip() or "General",
        status="pending",
        uploaded_by=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    asyncio.create_task(run_ingestion(doc.id, state.embedder, state.vector_store))
    record_activity("document", f"Document '{safe_name}' uploaded by {user.username}")
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    zones = require_zone_scope(user, None)
    q = db.query(Document).order_by(Document.id.desc())
    if zones:
        q = q.filter(Document.zone.in_(zones))
    return q.all()


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(
    document_id: int,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_zone_access(user, doc.zone)
    try:
        state.vector_store.delete(filters={"modality": "document", "document_id": document_id})
    except Exception:  # noqa: BLE001
        pass
    try:
        shutil.rmtree(Path(doc.storage_path).parent, ignore_errors=True)
        from app.services.media_storage import media_delete

        media_delete(f"uploads/{Path(doc.storage_path).parent.name}/{Path(doc.storage_path).name}")
    except Exception:  # noqa: BLE001
        pass
    db.delete(doc)
    db.commit()
    record_activity("document", f"Document '{doc.filename}' deleted")
    return MessageResponse(message=f"Document '{doc.filename}' deleted")


@router.post("/{document_id}/retry", response_model=MessageResponse)
def retry_document(
    document_id: int,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_zone_access(user, doc.zone)
    doc.status = "pending"
    doc.error = ""
    db.commit()
    asyncio.create_task(run_ingestion(doc.id, state.embedder, state.vector_store))
    return MessageResponse(message=f"Re-processing '{doc.filename}'")
