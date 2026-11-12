"""Embedding abstraction: text and images share one CLIP vector space."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_text(self, text: str) -> np.ndarray: ...

    @abstractmethod
    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray: ...

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        return np.stack([self.embed_image(img) for img in images_bgr])

    @property
    @abstractmethod
    def device(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...


class FakeEmbedder(Embedder):
    """Deterministic offline embedder for tests (no model download)."""

    def __init__(self, dim: int = 64):
        self._dim = dim

    def _vec(self, seed_text: str) -> np.ndarray:
        digest = hashlib.md5(seed_text.encode("utf-8")).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        vec = rng.normal(size=self._dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm).astype(np.float32) if norm else vec

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(f"text:{t}") for t in texts])

    def embed_text(self, text: str) -> np.ndarray:
        return self._vec(f"text:{text}")

    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray:
        return self._vec(f"image:{image_bgr.shape}:{float(np.mean(image_bgr)):.2f}")

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        return np.stack([self.embed_image(img) for img in images_bgr])

    @property
    def device(self) -> str:
        return "none"

    @property
    def dimension(self) -> int:
        return self._dim
