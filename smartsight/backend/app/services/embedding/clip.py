"""OpenCLIP embedding service (CPU by default, GPU optional).

One model instance is shared by the live camera and the video indexer.
Inference is serialised under a lock; callers batch images so CPU inference
amortises the per-forward overhead.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from app.core.config import get_settings
from app.services.embedding.base import Embedder

logger = logging.getLogger(__name__)


class ClipEmbedder(Embedder):
    def __init__(self, model: str | None = None, pretrained: str | None = None, device: str | None = None):
        settings = get_settings()
        self._model_name = model or settings.clip_model
        self._pretrained = pretrained or settings.clip_pretrained
        self._device_choice = device or settings.clip_device
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._device = "cpu"
        self._lock = threading.Lock()
        self._dimension: int | None = None

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            import open_clip
            import torch

            if self._device_choice == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = self._device_choice
            if self._device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA requested but unavailable; using CPU")
                self._device = "cpu"

            logger.info("Loading CLIP %s (%s) on %s", self._model_name, self._pretrained, self._device)
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained, device=self._device
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = open_clip.get_tokenizer(self._model_name)
            self._dimension = int(model.visual.output_dim)
            logger.info("CLIP ready (dim=%d, device=%s)", self._dimension, self._device)

    def ensure_loaded(self) -> None:
        if self._model is None:
            self._load()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    # ----------------------------------------------------------------- embed
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        self.ensure_loaded()
        import torch

        with self._lock, torch.no_grad():
            tokens = self._tokenizer(texts).to(self._device)
            features = self._model.encode_text(tokens).float()
            features = features / features.norm(dim=-1, keepdim=True)
            return features.cpu().numpy().astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]

    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray:
        return self.embed_images_batch([image_bgr])[0]

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        """Embed N BGR images in one or more forward passes -> (N, dim)."""
        if not images_bgr:
            return np.zeros((0, self.dimension), dtype=np.float32)
        self.ensure_loaded()
        import torch
        from PIL import Image

        batch_size = 16
        out: list[np.ndarray] = []
        with self._lock, torch.no_grad():
            for start in range(0, len(images_bgr), batch_size):
                tensors = []
                for image in images_bgr[start : start + batch_size]:
                    rgb = np.ascontiguousarray(image[..., ::-1])  # BGR -> RGB
                    tensors.append(self._preprocess(Image.fromarray(rgb)))
                batch = torch.stack(tensors).to(self._device)
                features = self._model.encode_image(batch).float()
                features = features / features.norm(dim=-1, keepdim=True)
                out.append(features.cpu().numpy().astype(np.float32))
        return np.concatenate(out, axis=0)

    # ------------------------------------------------------------ properties
    @property
    def device(self) -> str:
        return self._device

    @property
    def dimension(self) -> int:
        self.ensure_loaded()
        return int(self._dimension or 0)

    @property
    def model_name(self) -> str:
        return self._model_name
