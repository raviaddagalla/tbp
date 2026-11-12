"""Embedding service abstraction.

A single embedder produces both text and image embeddings in the SAME
vector space (CLIP does this natively), which is what makes unified
video + document search possible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Return normalized float32 embeddings, shape (len(texts), dim)."""

    @abstractmethod
    def embed_text(self, text: str) -> np.ndarray:
        """Return normalized embedding for a single text, shape (dim,)."""

    @abstractmethod
    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray:
        """Embed a single BGR image (OpenCV format), normalized (dim,)."""

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        """Embed N BGR images in one forward pass -> (N, dim) normalized."""
        return np.stack([self.embed_image(img) for img in images_bgr])

    @property
    @abstractmethod
    def device(self) -> str:
        """Human-readable inference device, e.g. 'cpu' or 'cuda'."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...


class FakeEmbedder(Embedder):
    """Deterministic embedder for tests / offline dev without CLIP."""

    def __init__(self, dim: int = 64):
        self._dim = dim
        self._device = "cpu-fake"
        self._rng = np.random.default_rng(7)

    def _vec(self, seed_text: str, image: bool = False) -> np.ndarray:
        h = abs(hash((seed_text, image))) % (2**32)
        v = np.zeros(self._dim, dtype=np.float32)
        self._rng = np.random.default_rng(h)
        v = self._rng.normal(size=self._dim).astype(np.float32)
        if image:
            v[0] += 2.0  # bias so text != image embeddings
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n else v

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_text(self, text: str) -> np.ndarray:
        return self._vec(text)

    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray:
        return self._vec(str(image_bgr.shape), image=True)

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        return np.stack([self._vec(str(img.shape), image=True) for img in images_bgr])

    @property
    def device(self) -> str:
        return self._device

    @property
    def dimension(self) -> int:
        return self._dim
