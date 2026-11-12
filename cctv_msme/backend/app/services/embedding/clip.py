"""CLIP embedding service (open_clip) with CPU/GPU flexibility.

- Lazy-loads the model on first use so the API can boot without it.
- Thread-safe: all inference happens under a single lock (safe for GPU
  and for serialized CPU inference). Callers may dispatch to a threadpool.
- Gracefully degrades to CPU when no CUDA device is available.
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
        cfg = get_settings()
        self._model_name = model or cfg.clip_model
        self._pretrained = pretrained or cfg.clip_pretrained
        self._device_choice = device or cfg.clip_device
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._device = "cpu"
        self._lock = threading.Lock()
        self._dimension: int | None = None

    # ---------------------------------------------------------------- load
    def _load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                import open_clip
                import torch
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "open_clip / torch are not installed. Install backend requirements "
                    "('pip install -r requirements.txt')."
                ) from exc

            if self._device_choice == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = self._device_choice

            if self._device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA requested but unavailable; falling back to CPU.")
                self._device = "cpu"

            logger.info("Loading CLIP model %s (%s) on %s ...", self._model_name, self._pretrained, self._device)
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained, device=self._device
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = open_clip.get_tokenizer(self._model_name)
            self._dimension = model.visual.output_dim
            logger.info("CLIP loaded (dim=%d, device=%s)", self._dimension, self._device)

    def _ensure(self) -> None:
        if self._model is None:
            self._load()

    # ------------------------------------------------------------- embed
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        self._ensure()
        import torch

        with self._lock, torch.no_grad():
            tokens = self._tokenizer(texts).to(self._device)
            emb = self._model.encode_text(tokens)
            emb = emb.float()
            emb = emb / emb.norm(dim=-1, keepdim=True)
            return emb.cpu().numpy().astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]

    def embed_image(self, image_bgr: np.ndarray) -> np.ndarray:
        return self.embed_images_batch([image_bgr])[0]

    def embed_images_batch(self, images_bgr: list[np.ndarray]) -> np.ndarray:
        """Embed several BGR frames/crops in ONE forward pass (batched).

        CPU inference has a large fixed overhead per forward (preprocess +
        transform + first-layer): batching N images amortizes it, so indexing
        a frame together with all its detection crops is several times faster
        than embedding each one under a separate lock acquisition.
        """
        self._ensure()
        import torch
        from PIL import Image

        batch_size = 16  # bounds the tensor size on CPU/GPU alike
        out: list[np.ndarray] = []
        with self._lock, torch.no_grad():
            for start in range(0, len(images_bgr), batch_size):
                xs = []
                for img in images_bgr[start : start + batch_size]:
                    rgb = np.ascontiguousarray(img[..., ::-1])  # BGR -> RGB
                    xs.append(self._preprocess(Image.fromarray(rgb)))
                x = torch.stack(xs).to(self._device)
                emb = self._model.encode_image(x)
                emb = emb.float()
                emb = emb / emb.norm(dim=-1, keepdim=True)
                out.append(emb.cpu().numpy().astype(np.float32))
        return np.concatenate(out, axis=0)

    # ---------------------------------------------------------- properties
    @property
    def device(self) -> str:
        try:
            self._ensure()
        except RuntimeError:
            pass
        return self._device

    @property
    def dimension(self) -> int:
        self._ensure()
        return int(self._dimension)
