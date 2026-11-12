"""Person ReID: OSNet embedder with a no-op fallback so cross-camera identity
never becomes a single point of failure (Phase 2)."""
from .embedder import NoopReidEmbedder, ReidEmbedder, get_reid_embedder  # noqa: F401
