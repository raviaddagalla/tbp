"""Chroma-backed vector store (persistent, local, no cloud)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np

from app.services.vectorstore.base import SearchResult, VectorStore

logger = logging.getLogger(__name__)

COLLECTION = "factory_intel"


def _norm_embedding(emb) -> np.ndarray:
    arr = np.asarray(emb, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    return arr


_OPS = {"$gte", "$lte", "$eq", "$in", "$ne", "$gt", "$lt"}


def _expand_filters(filters: dict | None) -> dict | None:
    """Chroma >=1.x requires exactly one operator per query, so rebuild
    the where clause: every top-level condition becomes its own clause
    (multi-operator dicts like {"$gte": a, "$lte": b} are split into one
    clause per operator) and clauses are joined with an explicit $and."""
    if not filters:
        return filters
    ands: list[dict] = []
    for key, cond in filters.items():
        if isinstance(cond, dict) and set(cond) <= _OPS and len(cond) > 1:
            for op, val in cond.items():
                ands.append({key: {op: val}})
        else:
            ands.append({key: cond})
    if len(ands) == 1:
        return ands[0]
    return {"$and": ands}


class ChromaStore(VectorStore):
    def __init__(self, persist_dir: str):
        import chromadb  # imported lazily; caller falls back if unavailable

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._col = self._client.get_or_create_collection(
            COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Chroma vector store ready at %s (count=%d)", persist_dir, self._col.count())

    def add(self, ids, embeddings, metadatas, texts=None) -> None:
        ids = [str(i) if isinstance(i, uuid.UUID) else i for i in ids]
        self._col.add(ids=ids, embeddings=_norm_embedding(embeddings), metadatas=metadatas, documents=texts)

    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]:
        if self._col.count() == 0:
            return []
        res = self._col.query(
            query_embeddings=_norm_embedding(embedding),
            n_results=top_k,
            where=_expand_filters(filters),
            include=["metadatas", "documents", "distances"],
        )
        out: list[SearchResult] = []
        for i, (dist, meta, doc) in enumerate(
            zip(res["distances"][0], res["metadatas"][0], res["documents"][0])
        ):
            score = float(max(0.0, 1.0 - float(dist)))  # cosine distance -> similarity
            out.append(
                SearchResult(id=res["ids"][0][i], score=score, metadata=meta or {}, text=doc or "")
            )
        return out

    def get(self, filters: dict | None = None, limit: int | None = None) -> list[SearchResult]:
        where = _expand_filters(filters)
        res = self._col.get(where=where, limit=limit, include=["metadatas", "documents", "embeddings"])
        out = []
        for i, meta in enumerate(res["metadatas"] or []):
            emb = res["embeddings"][i] if res.get("embeddings") is not None else None
            out.append(
                SearchResult(
                    id=res["ids"][i],
                    score=0.0,
                    metadata=meta or {},
                    text=res["documents"][i] or "",
                    embedding=emb,
                )
            )
        return out

    def count(self, filters: dict | None = None) -> int:
        if filters is None:
            return self._col.count()
        where = _expand_filters(filters)
        res = self._col.get(where=where, include=["metadatas"])
        return len(res["ids"])

    def delete(self, ids=None, filters=None) -> int:
        before = self._col.count()
        if ids:
            self._col.delete(ids=[str(i) for i in ids])
        elif filters:
            hits = self._col.get(where=_expand_filters(filters))
            if hits["ids"]:
                self._col.delete(ids=hits["ids"])
        return before - self._col.count()

    def compact(self) -> dict:
        """Compact the HNSW index (bounds tombstone bloat).

        Prefers Chroma's native compact(); falls back to a full export +
        rebuild when the installed version doesn't expose it.
        """
        import chromadb

        total = self._col.count()
        rebuild = False
        if hasattr(self._col, "compact"):
            try:
                self._col.compact()
                return {"backend": "chroma", "rows": total, "mode": "hnsw-compact"}
            except Exception as exc:  # noqa: BLE001 - fall back to rebuild
                logger.warning("Chroma compact() failed (%s); rebuilding collection.", exc)
        rebuild = True

        data = self._col.get(include=["embeddings", "metadatas", "documents"])
        ids = list(data["ids"])
        if not ids:
            return {"backend": "chroma", "rows": 0, "mode": "no-op"}
        try:
            self._client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001
            pass
        self._col = self._client.get_or_create_collection(
            COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        # Re-add in chunks to keep memory bounded on large collections.
        for i in range(0, len(ids), 512):
            chunk = slice(i, i + 512)
            self._col.add(
                ids=ids[chunk],
                embeddings=np.asarray(data["embeddings"][chunk], dtype=np.float32),
                metadatas=data["metadatas"][chunk],
                documents=data["documents"][chunk],
            )
        logger.info("Chroma collection rebuilt (was %d rows)", total)
        return {"backend": "chroma", "rows": total, "mode": "rebuild" if rebuild else "hnsw-compact"}

    def name(self) -> str:
        return "chroma"
