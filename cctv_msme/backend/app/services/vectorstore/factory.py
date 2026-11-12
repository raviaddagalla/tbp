"""Vector store factory with automatic backend selection."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import get_settings
from app.services.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)


def _build() -> VectorStore:
    settings = get_settings()
    backend = (settings.vector_store_backend or "auto").strip().lower()
    is_postgres = settings.database_url.startswith(("postgres", "postgresql"))

    if backend in ("auto", "pgvector", "postgres") and is_postgres:
        from app.services.vectorstore.postgres_store import PostgresVectorStore

        try:
            return PostgresVectorStore()
        except Exception as exc:  # noqa: BLE001
            if backend != "auto":
                raise
            logger.warning("pgvector unavailable (%s); falling back to local store.", exc)

    if backend in ("auto", "chroma"):
        try:
            from app.services.vectorstore.chroma_store import ChromaStore

            return ChromaStore(settings.chroma_dir)
        except Exception as exc:  # noqa: BLE001 - fall back rather than crash
            logger.warning("Chroma unavailable (%s); falling back to NumPy store.", exc)
    from app.services.vectorstore.numpy_store import NumpyStore

    return NumpyStore(str(settings.data_dir / "vectorstore_numpy"))


@lru_cache
def get_vector_store() -> VectorStore:
    store = _build()
    logger.info("Vector store backend in use: %s", store.name())
    return store
