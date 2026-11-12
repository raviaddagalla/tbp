"""Vector store correctness: add/query/delete/count/filter/compact parity
between the NumPy and Chroma backends, plus the NumPy hard cap."""
from __future__ import annotations

import os

import numpy as np
import pytest


def _make_store(tmp_path, backend: str):
    os.environ["VECTOR_STORE_BACKEND"] = backend
    if backend == "chroma":
        from app.services.vectorstore.chroma_store import ChromaStore

        return ChromaStore(str(tmp_path / "chroma"))
    from app.services.vectorstore.numpy_store import NumpyStore

    return NumpyStore(str(tmp_path / "numpy"))


def _random_embeddings(n: int, dim: int = 32) -> np.ndarray:
    rng = np.random.default_rng(42)
    v = rng.normal(size=(n, dim)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


@pytest.mark.parametrize("backend", ["numpy", "chroma"])
def test_add_query_delete_roundtrip(tmp_path, backend):
    store = _make_store(tmp_path, backend)
    embs = _random_embeddings(4)
    store.add(
        ["a", "b", "c", "d"],
        embs,
        [
            {"modality": "video", "camera_id": 1, "zone": "Z1", "ts_epoch": 100.0},
            {"modality": "video", "camera_id": 1, "zone": "Z1", "ts_epoch": 200.0},
            {"modality": "video", "camera_id": 2, "zone": "Z2", "ts_epoch": 300.0},
            {"modality": "document", "document_id": 7, "zone": "Z2", "ts_epoch": 400.0},
        ],
    )
    assert store.count() == 4
    assert store.count({"modality": "video"}) == 3
    assert store.count({"camera_id": 1}) == 2
    assert store.count({"zone": "Z2"}) == 2

    # Nearest neighbour of a is a itself (cosine ~1)
    hits = store.query(embs[0], top_k=1)
    assert hits[0].id == "a"
    assert hits[0].score > 0.99

    # Filtered query only returns matching rows
    hits = store.query(embs[0], top_k=4, filters={"camera_id": 2})
    assert all(h.metadata["camera_id"] == 2 for h in hits)

    # Range filter on ts_epoch
    hits = store.query(embs[0], top_k=4, filters={"ts_epoch": {"$gte": 150.0, "$lte": 350.0}})
    assert {h.id for h in hits} == {"b", "c"}

    # delete by ids
    assert store.delete(ids=["a"]) == 1
    assert store.count() == 3

    # delete by filter
    assert store.delete(filters={"modality": "video"}) == 2
    assert store.count() == 1
    assert store.count({"modality": "document"}) == 1

    # get() respects filters
    got = store.get(filters={"zone": "Z2"})
    assert len(got) == 1 and got[0].id == "d"


@pytest.mark.parametrize("backend", ["numpy", "chroma"])
def test_compact_is_idempotent(tmp_path, backend):
    store = _make_store(tmp_path, backend)
    embs = _random_embeddings(6)
    store.add([str(i) for i in range(6)], embs, [{"modality": "video", "camera_id": i % 3} for i in range(6)])
    store.delete(ids=["1", "3"])
    assert store.count() == 4
    result = store.compact()
    assert result["rows"] == 4
    assert store.count() == 4
    # Queries still work after compaction
    hits = store.query(embs[2], top_k=3)
    assert len(hits) == 3


def test_numpy_store_hard_cap(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "numpy_store_max_vectors", 5, raising=False)
    os.environ["VECTOR_STORE_BACKEND"] = "numpy"
    from app.services.vectorstore.numpy_store import NumpyStore

    store = NumpyStore(str(tmp_path / "numpy"))
    embs = _random_embeddings(6)
    store.add([str(i) for i in range(5)], embs[:5], [{"modality": "video", "camera_id": 1}] * 5)
    with pytest.raises(RuntimeError, match="hard cap"):
        store.add(["x"], embs[5:], [{"modality": "video", "camera_id": 1}])


def test_numpy_store_persists_across_reopen(tmp_path):
    from app.services.vectorstore.numpy_store import NumpyStore

    path = str(tmp_path / "numpy")
    store = NumpyStore(path)
    embs = _random_embeddings(3)
    store.add(["p1", "p2", "p3"], embs, [{"modality": "video", "camera_id": 1}] * 3)
    store.delete(ids=["p2"])

    reopened = NumpyStore(path)
    assert reopened.count() == 2
    assert reopened.count({"camera_id": 1}) == 2
