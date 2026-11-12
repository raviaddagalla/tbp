"""Document ingestion: parse -> chunk -> embed -> store (background task)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Document
from app.services.activity_feed import record as record_activity
from app.services.documents.chunker import chunk_pages
from app.services.documents.parser import parse_file
from app.utils.video import utcnow

logger = logging.getLogger(__name__)

_locks: dict[int, asyncio.Lock] = {}


async def run_ingestion(document_id: int, embedder, vector_store) -> None:
    """Ingest a document in the background, updating status as it goes."""
    lock = _locks.setdefault(document_id, asyncio.Lock())
    async with lock:
        db = SessionLocal()
        try:
            doc = db.get(Document, document_id)
            if not doc:
                return
            doc.status = "processing"
            db.commit()
        finally:
            db.close()

        try:
            path = Path(doc.storage_path)
            if not path.is_file():
                # Uploaded from another laptop -> pull from the shared bucket.
                from app.services.media_storage import media_get

                rel = str(path.relative_to(get_settings().uploads_dir)).replace("\\", "/")
                data = media_get(f"uploads/{rel}")
                if data is None:
                    raise FileNotFoundError(doc.storage_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            pages, ocr_used = await asyncio.get_event_loop().run_in_executor(
                None, parse_file, path, doc.doc_type
            )
            chunks = chunk_pages(pages)

            def _embed():
                texts = [c.text for c in chunks]
                embs = []
                for i in range(0, len(texts), 32):
                    embs.extend(embedder.embed_texts(texts[i : i + 32]).tolist())
                return embs

            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(None, _embed)

            ids = [str(uuid.uuid4()) for _ in chunks]
            metas = []
            for c, emb in zip(chunks, embeddings):
                metas.append(
                    {
                        "modality": "document",
                        "document_id": doc.id,
                        "filename": doc.filename,
                        "zone": doc.zone or "General",
                        "page": c.page,
                        "section": c.section or "General",
                        "chunk_idx": c.index,
                        "chunk_text": c.text,
                        "timestamp": utcnow().isoformat(),
                    }
                )
            vector_store.add(ids, embeddings, metas, texts=[c.text for c in chunks])

            db = SessionLocal()
            try:
                d = db.get(Document, document_id)
                if d:
                    d.status = "processed"
                    d.pages = len(pages)
                    d.chunk_count = len(chunks)
                    d.ocr_used = ocr_used
                    d.error = ""
                    db.commit()
            finally:
                db.close()
            record_activity("document", f"Document '{doc.filename}' indexed ({len(chunks)} chunks)")
            logger.info("Document %s processed: %d chunks", doc.filename, len(chunks))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Document ingestion failed for %s", doc.filename)
            db = SessionLocal()
            try:
                d = db.get(Document, document_id)
                if d:
                    d.status = "failed"
                    d.error = str(exc)[:500]
                    db.commit()
            finally:
                db.close()
            record_activity("document", f"Document '{doc.filename}' failed: {str(exc)[:120]}")
