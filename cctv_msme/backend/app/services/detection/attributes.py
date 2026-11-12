"""Zero-shot attribute extraction for detected objects (Phase 1).

Uses the shared CLIP space: the crop embedding is compared against small
prompt sets (colors, clothing, PPE) and the most similar prompt wins. No
extra model, no downloads — just a few extra embed_text calls per object.

The prompt text embeddings are computed ONCE (lazily, thread-safe) and
cached: per-object scoring then becomes one small matrix multiply, instead
of a full CLIP text forward pass for every crop of every frame.
"""
from __future__ import annotations

import threading

import numpy as np

# (attribute_key, prompt list). Prompts are ranked by CLIP similarity.
_ATTR_SETS: dict[str, list[str]] = {
    "attr_color": [
        "a person or object that is red",
        "a person or object that is orange",
        "a person or object that is yellow",
        "a person or object that is green",
        "a person or object that is blue",
        "a person or object that is purple",
        "a person or object that is pink",
        "a person or object that is white",
        "a person or object that is black",
        "a person or object that is gray",
        "a person or object that is brown",
    ],
    "attr_clothing": [
        "a person wearing a high-visibility safety vest",
        "a person wearing a plain t-shirt",
        "a person wearing a jacket",
        "a person wearing coveralls or overalls",
    ],
    "attr_ppe": [
        "a person wearing a safety helmet or hard hat",
        "a person with no helmet or head protection",
    ],
}

# Fallback values when the class is not a person (color still applies).
_CLASS_DEFAULT_ATTRS = {"attr_clothing": "n/a", "attr_ppe": "n/a"}

# Lazily-built (prompt-matrix, key-boundaries) cache, shared across threads.
_ATTR_CACHE: tuple[np.ndarray, list[tuple[int, int]]] | None = None
_ATTR_CACHE_LOCK = threading.Lock()
_ATTR_KEYS = list(_ATTR_SETS.keys())
_ALL_PROMPTS = [p for prompts in _ATTR_SETS.values() for p in prompts]


def _attr_matrix(embedder) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """One-time text embedding of every attribute prompt -> (M, D) matrix.

    Returns (matrix, [(start, end), ...]) with one (start, end) per key.
    """
    global _ATTR_CACHE
    if _ATTR_CACHE is not None:
        return _ATTR_CACHE
    with _ATTR_CACHE_LOCK:
        if _ATTR_CACHE is None:
            emb = np.asarray(embedder.embed_texts(_ALL_PROMPTS), dtype=np.float32)
            bounds: list[tuple[int, int]] = []
            idx = 0
            for prompts in _ATTR_SETS.values():
                bounds.append((idx, idx + len(prompts)))
                idx += len(prompts)
            _ATTR_CACHE = (emb, bounds)
    return _ATTR_CACHE


def extract_attributes(embedder, crop_embedding: np.ndarray, class_name: str) -> dict:
    """Return {attr_color: ..., attr_clothing: ..., attr_ppe: ...}."""
    attrs: dict[str, str] = {"attr_color": "unknown", "attr_clothing": "n/a", "attr_ppe": "n/a"}
    if class_name != "person":
        attrs.update(_CLASS_DEFAULT_ATTRS)
    try:
        emb = np.asarray(crop_embedding, dtype=np.float32).reshape(-1)
        matrix, bounds = _attr_matrix(embedder)
        scores = matrix @ emb  # (M, D) x (D,) — microseconds on cached embeddings
        for key_idx, key in enumerate(_ATTR_KEYS):
            if class_name != "person" and key != "attr_color":
                continue
            start, end = bounds[key_idx]
            best = int(np.argmax(scores[start:end]))
            attrs[key] = _ALL_PROMPTS[start + best].split(" is ")[-1].rstrip(".")
    except Exception:  # noqa: BLE001 - attributes are best-effort metadata
        pass
    return attrs
