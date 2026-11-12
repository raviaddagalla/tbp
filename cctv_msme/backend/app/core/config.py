"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_file_path() -> str:
    """Locate the repo-root .env whether running from the root, backend/, or a Docker WORKDIR."""
    for base in (Path.cwd(), Path.cwd().parent, _REPO_ROOT):
        candidate = base / ".env"
        if candidate.is_file():
            return str(candidate)
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file_path(), env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Factory Intelligence Platform"
    secret_key: str = "dev-secret-key-change-me-please-use-a-stronger-one"
    # dev | production — production refuses to boot on the dev secret key
    environment: str = "dev"
    access_token_expire_minutes: int = 480
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Storage
    database_url: str = "sqlite:///./data/factory.db"
    data_dir: Path = Path("./data")

    # Vector store
    # auto -> pgvector when DATABASE_URL is Postgres, else Chroma/NumPy
    vector_store_backend: str = "auto"
    chroma_dir: str = "./data/vectorstore"

    # Remote media (Cloudflare R2, S3-compatible). When enabled, thumbs,
    # uploaded videos and clips are mirrored to the bucket so every laptop
    # sees the same media. Local disk stays as a cache.
    media_remote_enabled: bool = False
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_region: str = "auto"

    # Camera workers run on this machine (set WORKER_ENABLED=false on a
    # second laptop that only browses, to avoid double-processing cameras)
    worker_enabled: bool = True

    # CLIP
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion400m_e32"
    clip_device: str = "auto"
    clip_inference_threads: int = 4

    # Camera ingestion defaults
    frame_sample_interval_default: float = 0.2  # 0.2s = 5 frames analysed per second
    clip_segment_seconds_default: int = 30
    retention_hours_default: int = 72
    preview_fps: int = 2

    # Video file upload (CCTV footage)
    video_upload_max_mb: int = 2048

    # LLM
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.2

    # OCR
    tesseract_cmd: str = ""

    # Anomaly detection
    anomaly_enabled_default: bool = False
    anomaly_threshold: float = 0.22
    anomaly_cooldown_seconds: int = 120
    anomaly_check_interval_seconds: int = 15

    # Edge-aware processing
    edge_adaptive_load: bool = True

    # Demo: seed 3 simulated cameras on first boot when no cameras exist
    seed_demo_sim_cameras: bool = False

    # Detection / tracking (Phase 1)
    detector_enabled_default: bool = True
    detector_model: str = "yolov8n"  # yolov8n | yolov8s | yolov8m
    detector_confidence_threshold: float = 0.35
    tracker_enabled_default: bool = True

    # Attribute extraction on detected object crops (Phase 1)
    attributes_enabled_default: bool = True

    # ReID for cross-camera identity (Phase 2)
    reid_enabled_default: bool = True
    reid_collection: str = "factory_intel_reid"
    # OSNet checkpoint (auto-downloaded from HuggingFace to <data_dir>/reid)
    reid_model: str = "osnet_x1_0_msmt17"  # ""|none|disabled = off
    reid_weights_path: str = ""  # local .pth override; empty = auto-download

    # Tracklet stitching (Phase 2): α·reid + β·time_fit + γ·adjacency
    stitch_weights: str = "1.0,1.0,1.0"

    # Batch reprocessing of recorded footage (Phase 3)
    batch_reprocess_enabled_default: bool = True
    batch_reprocess_after_hours: int = 24
    batch_reprocess_window_seconds: int = 16
    batch_reprocess_stride: int = 8

    # Vector store limits / maintenance (Phase 0)
    numpy_store_max_vectors: int = 50000
    compaction_hour_utc: int = 3  # nightly Chroma compaction at 03:00 UTC

    # Signed update packages (Phase 4)
    update_public_key_path: str = ""  # PEM Ed25519 public key; empty = unsigned mode

    # Auth (Phase 0)
    login_rate_limit: str = "10/minute"
    media_token_ttl_minutes: int = 5

    # Derived paths
    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reid_dir(self) -> Path:
        return self.data_dir / "reid"

    @property
    def video_uploads_dir(self) -> Path:
        return self.data_dir / "uploads" / "videos"

    @property
    def is_dev(self) -> bool:
        return self.secret_key == "dev-secret-key-change-me-please-use-a-stronger-one"

    @property
    def stitch_weight_list(self) -> list[float]:
        parts = [p.strip() for p in self.stitch_weights.split(",") if p.strip()][:3]
        return [float(p) for p in parts] or [1.0, 1.0, 1.0]

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.thumbs_dir,
            self.clips_dir,
            self.uploads_dir,
            self.video_uploads_dir,
            self.reid_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production" and s.is_dev:
        raise RuntimeError(
            "Refusing to start: ENVIRONMENT=production with the default dev SECRET_KEY. "
            "Set a strong SECRET_KEY in .env before deploying."
        )
    s.ensure_dirs()
    return s

