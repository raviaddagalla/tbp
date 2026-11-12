"""SmartSight settings (environment / .env backed)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def _env_file_path() -> str:
    for base in (Path.cwd(), Path.cwd().parent, REPO_DIR):
        candidate = base / ".env"
        if candidate.is_file():
            return str(candidate)
    return str(REPO_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file_path(), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SmartSight"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Storage
    data_dir: Path = BACKEND_DIR / "data"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'smartsight.db').as_posix()}"
    chroma_dir: str = str(BACKEND_DIR / "data" / "vectorstore")

    # Vision models. CPU by default; set CLIP_DEVICE=cuda on a GPU machine.
    detector_model: str = str(BACKEND_DIR / "yolov8n.pt")
    detector_confidence_threshold: float = 0.35
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion400m_e32"
    clip_device: str = "cpu"
    # 0 = auto (half the logical cores, capped at 4)
    torch_threads: int = 0

    # Live camera defaults (runtime values live in the camera_config row)
    stream_url_default: str = "http://192.168.0.132:81/stream"
    live_fps_default: float = 2.0
    live_index_interval_default: float = 3.0
    camera_connect_timeout: float = 6.0
    camera_read_timeout: float = 10.0

    # Uploaded video indexing
    sample_fps_default: float = 2.0
    video_upload_max_mb: int = 2048
    # Safety cap so one huge upload cannot monopolise the laptop for hours.
    video_index_max_frames: int = 6000
    thumbnail_max_width: int = 720

    # Built-in demo scene used by the simulated camera source and tests.
    demo_scene_path: str = str(BACKEND_DIR / "app" / "assets" / "demo_scene.jpg")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.thumbs_dir, self.snapshots_dir, self.recordings_dir, Path(self.chroma_dir)):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
