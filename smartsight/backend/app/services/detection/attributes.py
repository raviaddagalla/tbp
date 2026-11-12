"""Zero-shot colour labelling for detected object crops.

Reuses the shared CLIP space: prompt embeddings are computed once and cached,
so labelling a crop is a single small matrix multiply.
"""
from __future__ import annotations

import threading

import numpy as np

COLOR_PROMPTS = [
    "a photo of something red",
    "a photo of something orange",
    "a photo of something yellow",
    "a photo of something green",
    "a photo of something blue",
    "a photo of something purple",
    "a photo of something pink",
    "a photo of something white",
    "a photo of something black",
    "a photo of something gray",
    "a photo of something brown",
]
COLOR_LABELS = ["red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "black", "gray", "brown"]

_cache: np.ndarray | None = None
_lock = threading.Lock()


def _prompt_matrix(embedder) -> np.ndarray:
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is None:
            _cache = np.asarray(embedder.embed_texts(COLOR_PROMPTS), dtype=np.float32)
    return _cache


def dominant_color(embedder, crop_embedding: np.ndarray) -> str:
    """Best-matching colour word for a crop, or '' on failure."""
    try:
        matrix = _prompt_matrix(embedder)
        scores = matrix @ np.asarray(crop_embedding, dtype=np.float32).reshape(-1)
        return COLOR_LABELS[int(np.argmax(scores))]
    except Exception:  # noqa: BLE001 - colour is optional metadata
        return ""
