"""Floor-plan graph calibration (Phase 2): camera adjacency edges + pins.

An admin uploads a floor-plan image, drags camera pins onto it and draws
directed edges between adjacent cameras with expected transit-time windows.
The stitching service (services/reid/stitching.py) only ever suggests
cross-camera candidates along these edges — no calibration, no trails.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_query_token, require_media_scope, require_roles
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Camera, CameraAdjacency, FloorPlan, User
from app.schemas import MessageResponse

router = APIRouter(tags=["floorplan"])


class AdjacencyEdgeIn(BaseModel):
    from_camera_id: int
    to_camera_id: int
    expected_transit_seconds_min: int = Field(default=5, ge=1, le=86400)
    expected_transit_seconds_max: int = Field(default=300, ge=1, le=86400)
    direction_label: str = ""


class AdjacencySetIn(BaseModel):
    edges: list[AdjacencyEdgeIn] = []


def _latest_floorplan(db: Session) -> FloorPlan | None:
    return db.query(FloorPlan).order_by(FloorPlan.created_at.desc()).first()


# ---------------------------------------------------------------- adjacency
@router.get("/cameras/adjacency", response_model=list[dict])
def list_adjacency(
    user: User = Depends(require_roles("supervisor", "admin")),
    db: Session = Depends(get_db),
):
    cams = {c.id: c.name for c in db.query(Camera).all()}
    edges = db.query(CameraAdjacency).order_by(CameraAdjacency.from_camera_id, CameraAdjacency.to_camera_id).all()
    return [
        {
            "id": e.id,
            "from_camera_id": e.from_camera_id,
            "from_camera_name": cams.get(e.from_camera_id, ""),
            "to_camera_id": e.to_camera_id,
            "to_camera_name": cams.get(e.to_camera_id, ""),
            "expected_transit_seconds_min": e.expected_transit_seconds_min,
            "expected_transit_seconds_max": e.expected_transit_seconds_max,
            "direction_label": e.direction_label,
            "floorplan_id": e.floorplan_id,
        }
        for e in edges
    ]


@router.put("/cameras/adjacency", response_model=MessageResponse)
def put_adjacency(
    body: AdjacencySetIn,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Replace the whole edge set (calibration is done per-site, rarely)."""
    valid_ids = {c.id for c in db.query(Camera.id).all()}
    for edge in body.edges:
        if edge.from_camera_id not in valid_ids or edge.to_camera_id not in valid_ids:
            raise HTTPException(status_code=400, detail="Unknown camera id in edge")
        if edge.from_camera_id == edge.to_camera_id:
            raise HTTPException(status_code=400, detail="Camera cannot be adjacent to itself")
        if edge.expected_transit_seconds_max < edge.expected_transit_seconds_min:
            raise HTTPException(
                status_code=400,
                detail="expected_transit_seconds_max must be >= expected_transit_seconds_min",
            )
    db.query(CameraAdjacency).delete()
    fp = _latest_floorplan(db)
    for edge in body.edges:
        db.add(
            CameraAdjacency(
                from_camera_id=edge.from_camera_id,
                to_camera_id=edge.to_camera_id,
                expected_transit_seconds_min=edge.expected_transit_seconds_min,
                expected_transit_seconds_max=edge.expected_transit_seconds_max,
                direction_label=edge.direction_label,
                floorplan_id=str(fp.id) if fp else "",
            )
        )
    db.commit()
    return MessageResponse(message=f"Saved {len(body.edges)} adjacency edge(s)")


# ---------------------------------------------------------------- floorplan
@router.get("/floorplan", response_model=dict)
def get_floorplan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fp = _latest_floorplan(db)
    if fp is None:
        return {"id": None, "name": "", "pins": {}, "image_url": ""}
    return {
        "id": fp.id,
        "name": fp.name,
        "pins": fp.pins_json or {},
        "image_url": "/api/floorplan/image",
    }


@router.post("/floorplan", response_model=dict)
def upload_floorplan(
    file: UploadFile = File(...),
    name: str = Form("Site Floor Plan"),
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(status_code=400, detail="Floor plan must be a JPG, PNG or WebP image")
    settings = get_settings()
    fp_dir = settings.data_dir / "floorplans"
    fp_dir.mkdir(parents=True, exist_ok=True)
    filename = f"floorplan_{int(time.time())}{ext if ext in ('.png', '.webp') else '.jpg'}"
    dest = fp_dir / filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    fp = FloorPlan(name=name, image_path=str(dest), pins_json={})
    db.add(fp)
    db.commit()
    db.refresh(fp)
    return {"id": fp.id, "name": fp.name, "pins": {}, "image_url": "/api/floorplan/image"}


@router.put("/floorplan/pins", response_model=MessageResponse)
def put_pins(
    body: dict,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Persist pin positions: {pins: {camera_id: {x, y}}} (percentages 0-100)."""
    fp = _latest_floorplan(db)
    if fp is None:
        raise HTTPException(status_code=404, detail="Upload a floor plan first")
    pins = body.get("pins") or {}
    valid_ids = {c.id for c in db.query(Camera.id).all()}
    cleaned = {}
    for key, pos in pins.items():
        try:
            cam_id = int(key)
        except (TypeError, ValueError):
            continue
        if cam_id not in valid_ids:
            continue
        cleaned[str(cam_id)] = {
            "x": round(min(100.0, max(0.0, float(pos.get("x", 0)))), 2),
            "y": round(min(100.0, max(0.0, float(pos.get("y", 0)))), 2),
        }
    fp.pins_json = cleaned
    db.commit()
    return MessageResponse(message=f"Saved {len(cleaned)} camera pin(s)")


@router.get("/floorplan/image")
def floorplan_image(
    request: Request,
    user: User = Depends(get_current_user_query_token),
    db: Session = Depends(get_db),
):
    """Floor-plan image for <img> tags (works with scoped media tokens)."""
    require_media_scope(user, request.url.path)
    fp = _latest_floorplan(db)
    if fp is None:
        raise HTTPException(status_code=404, detail="No floor plan uploaded")
    path = Path(fp.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Floor plan image missing")
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
    return FileResponse(path, media_type=media_type)
