"""Process-wide vector store singletons (scene + object collections)."""
from __future__ import annotations

import threading

from app.core.config import get_settings
from app.services.vectorstore.chroma_store import OBJECT_COLLECTION, SCENE_COLLECTION, ChromaStore

_lock = threading.Lock()
_stores: tuple[ChromaStore, ChromaStore] | None = None


def get_stores() -> tuple[ChromaStore, ChromaStore]:
    global _stores
    if _stores is None:
        with _lock:
            if _stores is None:
                settings = get_settings()
                _stores = (
                    ChromaStore(settings.chroma_dir, SCENE_COLLECTION),
                    ChromaStore(settings.chroma_dir, OBJECT_COLLECTION),
                )
    return _stores


def get_scene_store() -> ChromaStore:
    return get_stores()[0]


def get_object_store() -> ChromaStore:
    return get_stores()[1]
