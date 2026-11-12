"""Analytics + system load + activity feed."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Camera, User
from app.schemas import (
    AnalyticsOverview,
    CameraDiagnostics,
    LoadStatus,
    SystemDiagnostics,
)
from app.services.analytics.service import overview
from app.services.activity_feed import recent
from app.state import state

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview", response_model=AnalyticsOverview)
def analytics_overview(user: User = Depends(require_roles("supervisor", "admin"))):
    return overview()


@router.get("/activity")
def activity_feed(limit: int = 30, user: User = Depends(get_current_user)):
    return recent(limit=min(limit, 100))


@router.get("/system/load", response_model=LoadStatus)
def system_load(user: User = Depends(require_roles("supervisor", "admin"))):
    wm = state.worker_manager
    return LoadStatus(
        active_cameras=len(wm.workers) if wm else 0,
        effective_sample_interval=wm.effective_sample_interval() if wm else 5,
        llm_provider=state.llm.provider if state.llm else "uninitialized",
        llm_model=state.settings.llm_model,
        embedding_device=state.embedder.device if state.embedder else "uninitialized",
        vector_store_backend=state.vector_store.name() if state.vector_store else "uninitialized",
        queue_depth=wm.queue_depth() if wm else 0,
    )


@router.get("/system/diagnostics", response_model=SystemDiagnostics)
def system_diagnostics(user: User = Depends(require_roles("supervisor", "admin"))):
    settings = get_settings()
    wm = state.worker_manager
    store = state.vector_store
    inflight = {cid: w._inflight for cid, w in wm.workers.items()} if wm else {}  # noqa: SLF001

    db = SessionLocal()
    try:
        cameras = db.query(Camera).order_by(Camera.id).all()
        cam_diag: list[CameraDiagnostics] = []
        for cam in cameras:
            counts = {"object": 0, "clip_event": 0}
            if store is not None:
                for modality in ("object", "clip_event"):
                    try:
                        counts[modality] = store.count(
                            filters={"modality": modality, "camera_id": cam.id}
                        )
                    except Exception:  # noqa: BLE001
                        counts[modality] = -1
            cam_diag.append(
                CameraDiagnostics(
                    id=cam.id,
                    name=cam.name,
                    zone=cam.zone,
                    status=cam.status,
                    last_seen_at=cam.last_seen_at,
                    connected_at=cam.connected_at,
                    last_error=cam.last_error,
                    frames_processed=cam.frames_processed,
                    frames_indexed=cam.frames_indexed,
                    alerts_count=cam.alerts_count,
                    inflight=inflight.get(cam.id, 0),
                    sample_interval_seconds=cam.sample_interval_seconds,
                    retention_hours=cam.retention_hours,
                    detector_enabled=cam.detector_enabled,
                    reid_enabled=cam.reid_enabled,
                    batch_reprocess_enabled=cam.batch_reprocess_enabled,
                    anomaly_enabled=cam.anomaly_enabled,
                    object_vectors=counts["object"],
                    clip_event_vectors=counts["clip_event"],
                )
            )
    finally:
        db.close()

    return SystemDiagnostics(
        vector_store_backend=store.name() if store else "uninitialized",
        queue_depth=wm.queue_depth() if wm else 0,
        effective_sample_interval=wm.effective_sample_interval() if wm else settings.frame_sample_interval_default,
        llm_provider=state.llm.provider if state.llm else "uninitialized",
        llm_model=settings.llm_model,
        embedding_device=state.embedder.device if state.embedder else "uninitialized",
        reid_model=settings.reid_model,
        data_dir=str(settings.data_dir.resolve()),
        retention_hours=settings.retention_hours_default,
        cameras=cam_diag,
    )
