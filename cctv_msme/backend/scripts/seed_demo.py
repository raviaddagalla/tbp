"""One-shot demo seed: users + simulated cameras + sample documents.

Usage:
    python -m scripts.seed_demo            # from backend/
    docker compose exec backend python -m scripts.seed_demo

Idempotent: existing users/cameras/documents are left untouched.
Runs the real CLIP embedder, so first use downloads the model.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.db.base import Base, SessionLocal, engine
from app.db.models import Document


async def _seed_docs() -> int:
    from app.services.documents.ingester import run_ingestion
    from app.state import init_state, state

    init_state()
    settings = get_settings()
    sample_dir = Path(__file__).resolve().parent.parent / "sample_data"
    db = SessionLocal()
    existing = {d.filename for d in db.query(Document).all()}
    count = 0
    try:
        for f in sorted(sample_dir.glob("*.txt")):
            if f.name in existing:
                continue
            dest_dir = settings.uploads_dir / f"demo-{f.stem}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f.name
            shutil.copy2(f, dest)
            doc = Document(
                filename=f.name,
                storage_path=str(dest),
                doc_type="text",
                status="pending",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            await run_ingestion(doc.id, state.embedder, state.vector_store)
            count += 1
    finally:
        db.close()
    return count


def main() -> None:
    from app.main import SEED_USERS, _seed

    Base.metadata.create_all(bind=engine)
    _seed()  # users + simulated cameras (only when empty)

    count = asyncio.run(_seed_docs())
    print("Seed complete.")
    print("  Users:", ", ".join(f"{u}/{p}" for u, p, *_ in SEED_USERS))
    print("  Demo documents indexed:", count)


if __name__ == "__main__":
    main()
