"""Chroma-backed persistent vector store.

SmartSight keeps two collections in the same directory:
  - `smartsight_scenes`  -> whole-frame CLIP embeddings
  - `smartsight_objects` -> cropped-object CLIP embeddings
so scene and object similarity are never mixed.
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.vectorstore.base import SearchResult, VectorStore

logger = logging.getLogger(__name__)

SCENE_COLLECTION = "smartsight_scenes"
OBJECT_COLLECTION = "smartsight_objects"

_OPS = {"$gte", "$lte", "$eq", "$in", "$ne", "$gt", "$lt"}


def _embeddings_array(embeddings) -> np.ndarray:
    arr = np.asarray(embeddings, dtype=np.float32)
    return arr[None, :] if arr.ndim == 1 else arr


def _expand_filters(filters: dict | None) -> dict | None:
    """Chroma allows one operator per condition: split and join with $and."""
    if not filters:
        return None
    clauses: list[dict] = []
    for key, condition in filters.items():
        if isinstance(condition, dict) and set(condition) <= _OPS and len(condition) > 1:
            clauses.extend({key: {op: value}} for op, value in condition.items())
        else:
            clauses.append({key: condition})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _clean_metadata(meta: dict) -> dict:
    """Chroma only accepts str/int/float/bool metadata values."""
    out: dict = {}
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, bool | int | float | str):
            out[key] = value
        else:
            out[key] = str(value)
    return out


class ChromaStore(VectorStore):
    def __init__(self, persist_dir: str, collection: str):
        import chromadb

        self._collection_name = collection
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._col = self._client.get_or_create_collection(collection, metadata={"hnsw:space": "cosine"})
        logger.info("Chroma collection '%s' ready (rows=%d)", collection, self._col.count())

    def add(self, ids, embeddings, metadatas, texts=None) -> None:
        self._col.add(
            ids=[str(i) for i in ids],
            embeddings=_embeddings_array(embeddings),
            metadatas=[_clean_metadata(m) for m in metadatas],
            documents=texts,
        )

    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]:
        if self._col.count() == 0:
            return []
        result = self._col.query(
            query_embeddings=_embeddings_array(embedding),
            n_results=max(1, top_k),
            where=_expand_filters(filters),
            include=["metadatas", "documents", "distances"],
        )
        out: list[SearchResult] = []
        for i, distance in enumerate(result["distances"][0]):
            out.append(
                SearchResult(
                    id=result["ids"][0][i],
                    score=float(max(0.0, 1.0 - float(distance))),
                    metadata=result["metadatas"][0][i] or {},
                    text=(result["documents"][0][i] or "") if result.get("documents") else "",
                )
            )
        return out

    def count(self, filters: dict | None = None) -> int:
        if filters is None:
            return int(self._col.count())
        return len(self._col.get(where=_expand_filters(filters) or {}, include=["metadatas"])["ids"])

    def delete(self, ids=None, filters=None) -> int:
        before = int(self._col.count())
        if ids:
            self._col.delete(ids=[str(i) for i in ids])
        elif filters:
            where = _expand_filters(filters)
            if where:
                hits = self._col.get(where=where)
                if hits["ids"]:
                    self._col.delete(ids=hits["ids"])
        elif ids is None and filters is None:
            return 0  # refuse an unscoped wipe; callers must be explicit
        return before - int(self._col.count())

    def name(self) -> str:
        return f"chroma:{self._collection_name}"
