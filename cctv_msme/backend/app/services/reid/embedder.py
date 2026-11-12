"""Person ReID embeddings for cross-camera identity (Phase 2).

`ReidEmbedder` runs the OSNet backbone (reid/osnet.py) with pretrained
MSMT17 weights. The weights are downloaded once from HuggingFace (repo
`kaiyangzhou/osnet`) into <data_dir>/reid and cached. `get_reid_embedder()`
mirrors the detector: it fails fast at startup and degrades to a no-op so
ingestion never dies over ReID.
"""
from __future__ import annotations

import logging
import shutil
import threading
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_SPECS: dict[str, dict[str, str]] = {
    "osnet_x1_0_msmt17": {
        "filename": (
            "osnet_x1_0_msmt17_combineall_256x128_amsgrad_ep150_stp60_"
            "lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth"
        ),
        "url": (
            "https://huggingface.co/kaiyangzhou/osnet/resolve/main/"
            "osnet_x1_0_msmt17_combineall_256x128_amsgrad_ep150_stp60_"
            "lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth"
        ),
    },
}

IMAGE_MEAN = (0.485, 0.456, 0.406)
IMAGE_STD = (0.229, 0.224, 0.225)
RESIZE_H, RESIZE_W = 256, 128  # torchreid's canonical ReID input size (h, w)
EMBED_DIM = 512
_BATCH = 32


def _download(url: str, dest: Path) -> None:
    """Stream a file to dest (tmp + atomic rename, like the numpy store)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)


def _normalize_tensor(t, mean, std):
    for c in range(3):
        t[:, c] = (t[:, c] - mean[c]) / std[c]
    return t


class ReidEmbedder:
    """Thread-safe OSNet ReID wrapper. Crops are BGR numpy frames (cv2)."""

    available = True

    def __init__(self, model_name: str = "osnet_x1_0_msmt17", weights_path: str = "", data_dir: str = "./data"):
        self.model_name = model_name
        self.weights_path = weights_path
        self.data_dir = Path(data_dir)
        self._model = None
        self._lock = threading.Lock()

    def _resolve_weights(self) -> Path:
        if self.weights_path:
            p = Path(self.weights_path)
            if p.is_file():
                return p
            raise FileNotFoundError(f"REID_WEIGHTS_PATH does not exist: {p}")
        spec = MODEL_SPECS.get(self.model_name)
        if spec is None:
            raise ValueError(f"Unknown REID_MODEL '{self.model_name}' (expected one of {sorted(MODEL_SPECS)})")
        dest = self.data_dir / "reid" / spec["filename"]
        if dest.is_file():
            return dest
        logger.info("Downloading ReID weights: %s -> %s", spec["filename"], dest)
        _download(spec["url"], dest)
        return dest

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        import torch

        from app.services.reid.osnet import OSBlock, OSNet

        with self._lock:
            if self._model is None:
                path = self._resolve_weights()
                state = torch.load(path, map_location="cpu", weights_only=True)
                if isinstance(state, dict) and "state_dict" in state:
                    state = state["state_dict"]
                state = {k[7:] if k.startswith("module.") else k: v for k, v in state.items()}
                num_classes = int(state["classifier.weight"].shape[0])
                model = OSNet(
                    num_classes,
                    blocks=[OSBlock, OSBlock, OSBlock],
                    layers=[2, 2, 2],
                    channels=[64, 256, 384, 512],
                )
                missing, unexpected = model.load_state_dict(state, strict=False)
                missing = [k for k in missing if not k.startswith("classifier")]
                if missing:
                    raise RuntimeError(f"ReID checkpoint missing keys: {missing[:8]}")
                if unexpected:
                    logger.debug("ReID checkpoint has %d unmatched keys", len(unexpected))
                model.eval()
                self._model = model
                logger.info(
                    "ReID embedder ready (%s, %d classes, %d params)",
                    self.model_name,
                    num_classes,
                    sum(p.numel() for p in model.parameters()),
                )
        return self._model

    def embed_people(self, crops: list[np.ndarray]) -> np.ndarray:
        """Embed person crops -> (N, 512) L2-normalized float32; (N, 0) on failure."""
        if not crops:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        try:
            import cv2
            import torch

            model = self._ensure_model()
            tensors = []
            for crop in crops:
                if crop is None or crop.size == 0:
                    crop = np.zeros((RESIZE_H, RESIZE_W, 3), dtype=np.uint8)
                img = crop[:, :, ::-1]  # BGR -> RGB (detection crops come from cv2 frames)
                img = cv2.resize(img, (RESIZE_W, RESIZE_H), interpolation=cv2.INTER_LINEAR)
                t = torch.from_numpy(img).permute(2, 0, 1).float().div_(255.0)
                tensors.append(_normalize_tensor(t, IMAGE_MEAN, IMAGE_STD))
            outs = []
            with torch.inference_mode():
                for i in range(0, len(tensors), _BATCH):
                    batch = torch.stack(tensors[i : i + _BATCH])
                    feats = model(batch)
                    feats = feats / feats.norm(dim=1, keepdim=True).clamp_min(1e-8)
                    outs.append(feats.cpu().numpy())
            return np.concatenate(outs).astype(np.float32)
        except Exception as exc:  # noqa: BLE001 - ReID must never kill ingestion
            logger.warning("reid embedding failed: %s", exc)
            return np.zeros((len(crops), 0), dtype=np.float32)


class NoopReidEmbedder:
    """Fallback when OSNet/weights are unavailable."""

    available = False

    def embed_people(self, crops: list[np.ndarray]) -> np.ndarray:
        return np.zeros((len(crops), 0), dtype=np.float32)


_reid_singleton = None
_reid_lock = threading.Lock()


def get_reid_embedder() -> ReidEmbedder | NoopReidEmbedder:
    """Cached ReID embedder; degrades to a no-op if the model cannot load."""
    global _reid_singleton
    if _reid_singleton is not None:
        return _reid_singleton
    with _reid_lock:
        if _reid_singleton is not None:
            return _reid_singleton
        from app.core.config import get_settings

        settings = get_settings()
        if settings.reid_model.strip().lower() in ("", "none", "disabled"):
            logger.info("ReID disabled (REID_MODEL=%s)", settings.reid_model)
            _reid_singleton = NoopReidEmbedder()
            return _reid_singleton
        try:
            emb = ReidEmbedder(settings.reid_model, settings.reid_weights_path, str(settings.data_dir))
            emb._ensure_model()  # fail fast so we degrade now, not mid-ingestion
            _reid_singleton = emb
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReID unavailable (%s); re-identification disabled", exc)
            _reid_singleton = NoopReidEmbedder()
        return _reid_singleton
