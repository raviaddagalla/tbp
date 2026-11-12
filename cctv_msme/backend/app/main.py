"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.db.base import Base, SessionLocal, engine
from app.db.models import Camera, User  # noqa: F401 - register models
from app.services.activity_feed import record as record_activity
from app.state import init_state, state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SEED_USERS = [
    ("admin", "admin123", "Factory Administrator", "admin", None),
    ("supervisor", "supervisor123", "Shift Supervisor", "supervisor", None),
    ("worker", "worker123", "Shop Floor Worker", "worker", "Loading Dock"),
]


def _ensure_schema() -> None:
    """create_all + lightweight column migrations for existing DBs (no Alembic).
    Adds missing columns to tables that already exist."""
    Base.metadata.create_all(bind=engine)
    import sqlalchemy as sa

    from app.db import models as m  # noqa: F401 - ensure all models registered

    try:
        if engine.dialect.name != "sqlite":
            return
        inspector = sa.inspect(engine)
        for table, table_cls in Base.metadata.tables.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col in Base.metadata.tables[table].columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(engine.dialect)
                default = ""
                if isinstance(col.type, sa.Boolean):
                    default = " DEFAULT 0"
                with engine.begin() as conn:
                    conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{col.name}" {coltype}{default}')
                logger.info("Migrated: added column %s.%s", table, col.name)
    except Exception as exc:  # noqa: BLE001 - schema migration is best-effort
        logger.warning("schema migration skipped: %s", exc)


def _seed() -> None:
    _ensure_schema()
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            from app.core.security import hash_password

            for username, pw, full, role, zone in SEED_USERS:
                db.add(
                    User(
                        username=username,
                        full_name=full,
                        hashed_password=hash_password(pw),
                        role=role,
                        zone=zone,
                    )
                )
            db.commit()
            logger.info("Seeded demo users: admin/admin123, supervisor/supervisor123, worker/worker123")
        settings = get_settings()
        if getattr(settings, "seed_demo_sim_cameras", False) and db.query(Camera).count() == 0:
            for name, zone, scene in [
                ("Loading Dock - CAM01", "Logistics", "loading_dock"),
                ("Storage Area - CAM02", "Warehouse", "storage"),
                ("Machine Zone - CAM03", "Production", "machine_zone"),
            ]:
                db.add(
                    Camera(
                        name=name,
                        rtsp_url=f"sim://{scene}",
                        zone=zone,
                        location_label=name,
                        sample_interval_seconds=settings.frame_sample_interval_default,
                        anomaly_enabled=settings.anomaly_enabled_default,
                    )
                )
            db.commit()
            logger.info("Seeded 3 simulated demo cameras (sim:// sources)")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed()
    init_state()
    if state.worker_manager:
        state.worker_manager.start_all()
        record_activity("system", "Platform started")
    from app.services.maintenance import start_maintenance_worker

    start_maintenance_worker()
    logger.info("%s started", state.settings.app_name)
    yield
    from app.services.maintenance import stop_maintenance_worker

    stop_maintenance_worker()
    if state.worker_manager:
        state.worker_manager.stop_all()
    logger.info("Shutdown complete")


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# Rate limiting (login brute-force protection)
from app.api.routers.auth import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routers import (  # noqa: E402
    alerts,
    analytics,
    auth,
    cameras,
    chat,
    documents,
    floorplan,
    search,
    streams,
    summaries,
    updates,
    users,
    ws,
)

for r in (
    auth,
    users,
    cameras,
    documents,
    search,
    chat,
    summaries,
    alerts,
    analytics,
    streams,
    floorplan,
    updates,
):
    app.include_router(r.router, prefix="/api")
app.include_router(ws.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "ready": state.ready,
        "llm_provider": state.llm.provider if state.llm else "uninitialized",
    }

