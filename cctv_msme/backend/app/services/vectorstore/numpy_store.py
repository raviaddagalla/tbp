"""Zero-dependency NumPy vector store.

Safety-net backend for environments where Chroma cannot be installed
(Python 3.13 wheels, offline installs, etc.). Cosine similarity in pure
NumPy with JSONL metadata persistence. Swap to Chroma/Milvus by setting
VECTOR_STORE_BACKEND=chroma.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from app.services.vectorstore.base import SearchResult, VectorStore

logger = logging.getLogger(__name__)


def _norm(arr: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.where(n == 0, 1.0, n)


class NumpyStore(VectorStore):
    def __init__(self, persist_dir: str):
        self._dir = Path(persist_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._emb_path = self._dir / "embeddings.npy"
        self._meta_path = self._dir / "metadata.jsonl"
        self._lock = threading.Lock()
        self._embeddings: np.ndarray = np.empty((0, 512), dtype=np.float32)
        self._metas: list[dict[str, Any]] = []
        self._dirty = False
        self._load()
        from app.core.config import get_settings

        self._max_vectors = get_settings().numpy_store_max_vectors

    # ------------------------------------------------------------- I/O
    def _load(self) -> None:
        if self._emb_path.exists():
            self._embeddings = _norm(np.load(self._emb_path))
        if self._meta_path.exists():
            with open(self._meta_path, "r", encoding="utf-8") as f:
                self._metas = [json.loads(line) for line in f if line.strip()]
        if self._embeddings.shape[0] != len(self._metas):
            n = min(self._embeddings.shape[0], len(self._metas))
            self._embeddings = self._embeddings[:n]
            self._metas = self._metas[:n]
        logger.info("NumPy vector store ready at %s (rows=%d)", self._dir, len(self._metas))

    def _save(self) -> None:
        if not self._dirty:
            return
        # NOTE: np.save appends ".npy" when the name lacks the suffix, so the
        # temp names must already end in .npy / .jsonl.
        tmp_emb = self._dir / "embeddings.tmp.npy"
        tmp_meta = self._dir / "metadata.tmp.jsonl"
        np.save(tmp_emb, self._embeddings)
        with open(tmp_meta, "w", encoding="utf-8") as f:
            for m in self._metas:
                f.write(json.dumps(m, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp_emb, self._emb_path)
        os.replace(tmp_meta, self._meta_path)
        self._dirty = False

    def _flush_maybe(self, force: bool = False) -> None:
        # Persist every 25 mutations and on demand to keep writes cheap.
        self._dirty = True
        if force or (len(self._metas) % 25 == 0):
            self._save()

    # ------------------------------------------------------------ store
    def add(self, ids, embeddings, metadatas, texts=None) -> None:
        arr = _norm(np.asarray(embeddings, dtype=np.float32))
        with self._lock:
            if len(self._metas) + len(ids) > self._max_vectors:
                raise RuntimeError(
                    f"NumPy vector store is at its hard cap of {self._max_vectors} vectors. "
                    "This backend is intended for demos only — set VECTOR_STORE_BACKEND=chroma "
                    "for production-sized collections."
                )
            for i, mid in enumerate(ids):
                meta = dict(metadatas[i])
                meta["_id"] = str(mid)
                if texts and i < len(texts):
                    meta["_text"] = texts[i]
                self._metas.append(meta)
            if self._embeddings.shape[0] == 0:
                self._embeddings = arr
            else:
                self._embeddings = np.vstack([self._embeddings, arr])
            self._flush_maybe()

    @staticmethod
    def _matches(meta: dict, filters: dict | None) -> bool:
        if not filters:
            return True
        for key, cond in filters.items():
            if isinstance(cond, dict) and set(cond.keys()).issubset({"$gte", "$lte", "$eq", "$in"}):
                val = meta.get(key)
                if "$in" in cond and val not in cond["$in"]:
                    return False
                if "$eq" in cond and val != cond["$eq"]:
                    return False
                if "$gte" in cond and val is not None and str(val) < str(cond["$gte"]):
                    return False
                if "$lte" in cond and val is not None and str(val) > str(cond["$lte"]):
                    return False
            else:
                if meta.get(key) != cond:
                    return False
        return True

    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]:
        with self._lock:
            if self._embeddings.shape[0] == 0:
                return []
            q = _norm(np.asarray(embedding, dtype=np.float32).reshape(1, -1))[0]
            scores = self._embeddings @ q
            order = np.argsort(-scores)
            out: list[SearchResult] = []
            for idx in order:
                if len(out) >= top_k:
                    break
                meta = self._metas[int(idx)]
                if self._matches(meta, filters):
                    out.append(
                        SearchResult(
                            id=meta.get("_id", ""),
                            score=float(scores[idx]),
                            metadata=meta,
                            text=meta.get("_text", ""),
                        )
                    )
            return out

    def get(self, filters: dict | None = None, limit: int | None = None) -> list[SearchResult]:
        with self._lock:
            out = []
            for idx, meta in enumerate(self._metas):
                if self._matches(meta, filters):
                    out.append(
                        SearchResult(
                            id=meta.get("_id", ""),
                            score=0.0,
                            metadata=meta,
                            text=meta.get("_text", ""),
                            embedding=self._embeddings[idx],
                        )
                    )
                    if limit and len(out) >= limit:
                        break
            return out

    def count(self, filters: dict | None = None) -> int:
        with self._lock:
            return sum(1 for m in self._metas if self._matches(m, filters))

    def delete(self, ids=None, filters=None) -> int:
        with self._lock:
            idset = set(ids or [])
            keep = []
            removed = 0
            for i, meta in enumerate(self._metas):
                if (idset and meta.get("_id") in idset) or (not idset and filters and self._matches(meta, filters)):
                    removed += 1
                else:
                    keep.append(i)
            if removed:
                self._metas = [self._metas[i] for i in keep]
                self._embeddings = self._embeddings[keep]
                self._flush_maybe(force=True)
            return removed

    def name(self) -> str:
        return "numpy"

    def compact(self) -> dict:
        with self._lock:
            self._save()
        return {"backend": "numpy", "rows": len(self._metas), "mode": "rewrite"}
