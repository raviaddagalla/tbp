"""ReID service tests (Phase 2).

The test env sets REID_MODEL=disabled, so the factory always yields the
no-op. Model-path tests construct `ReidEmbedder` directly with a local
checkpoint of random weights (never downloads from HuggingFace).
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.reid import NoopReidEmbedder, get_reid_embedder
from app.services.reid.embedder import ReidEmbedder


def _crop(rng, h=96, w=48):
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return img


def _random_checkpoint(path, num_classes=751):
    import torch

    from app.services.reid.osnet import osnet_x1_0

    model = osnet_x1_0(num_classes=num_classes)
    torch.save(model.state_dict(), path)
    return path


def test_get_reid_embedder_disabled_returns_noop():
    emb = get_reid_embedder()
    assert isinstance(emb, NoopReidEmbedder)
    feats = emb.embed_people([_crop(np.random.default_rng(1)) for _ in range(3)])
    assert feats.shape == (3, 0)


def test_reid_embedder_shape_and_normalization(tmp_path):
    rng = np.random.default_rng(2)
    checkpoint = _random_checkpoint(tmp_path / "osnet.pth")
    emb = ReidEmbedder("osnet_x1_0_msmt17", weights_path=str(checkpoint), data_dir=str(tmp_path))
    emb._ensure_model()
    feats = emb.embed_people([_crop(rng), _crop(rng, 120, 60)])
    assert feats.shape == (2, 512)
    assert np.allclose(np.linalg.norm(feats, axis=1), 1.0, atol=1e-4)


def test_reid_embedder_same_crop_high_similarity(tmp_path):
    rng = np.random.default_rng(3)
    checkpoint = _random_checkpoint(tmp_path / "osnet.pth")
    emb = ReidEmbedder("osnet_x1_0_msmt17", weights_path=str(checkpoint), data_dir=str(tmp_path))
    crop = _crop(rng)
    feats = emb.embed_people([crop, crop.copy()])
    sim = float(feats[0] @ feats[1])
    assert sim > 0.99


def test_reid_embedder_unknown_model_raises(tmp_path):
    emb = ReidEmbedder("bogus_model", data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="REID_MODEL"):
        emb._ensure_model()


def test_reid_embedder_missing_weights_path_raises(tmp_path):
    emb = ReidEmbedder("osnet_x1_0_msmt17", weights_path=str(tmp_path / "nope.pth"), data_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        emb._ensure_model()


def test_reid_embedder_corrupt_checkpoint_degrades(tmp_path):
    corrupt = tmp_path / "bad.pth"
    corrupt.write_bytes(b"not a checkpoint")
    emb = ReidEmbedder("osnet_x1_0_msmt17", weights_path=str(corrupt), data_dir=str(tmp_path))
    feats = emb.embed_people([_crop(np.random.default_rng(4))])
    assert feats.shape == (1, 0)  # degraded, never raises


def test_reid_embedder_empty_input(tmp_path):
    checkpoint = _random_checkpoint(tmp_path / "osnet.pth")
    emb = ReidEmbedder("osnet_x1_0_msmt17", weights_path=str(checkpoint), data_dir=str(tmp_path))
    assert emb.embed_people([]).shape == (0, 512)
