"""SmartSight FastAPI entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.torch_setup import configure_torch_threads
from app.db.base import Base, engine
from app.db import models  # noqa: F401 - register ORM models
from app.services.runtime import ai_status, get_runtime, init_runtime, shutdown_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    configure_torch_threads(settings.torch_threads)
    init_runtime()
    logger.info("SmartSight ready")
    yield
    shutdown_runtime()
    logger.info("SmartSight stopped")


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routers import camera, media, recordings, search, system  # noqa: E402

app.include_router(system.router, prefix="/api")
app.include_router(camera.router, prefix="/api")
app.include_router(recordings.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(media.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    runtime = get_runtime()
    return {
        "status": "ok",
        "app": settings.app_name,
        "camera": runtime.camera.stats()["status"],
        "monitoring": runtime.camera.running,
        "ai": ai_status(),
    }
