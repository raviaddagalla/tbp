"""Thumbnail and snapshot media endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings

router = APIRouter(prefix="/media", tags=["media"])


def _serve(directory: Path, filename: str):
    safe = Path(filename).name
    path = (directory / safe).resolve()
    if directory.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/thumb/{filename}")
def thumbnail(filename: str):
    return _serve(get_settings().thumbs_dir, filename)


@router.get("/snapshot/{filename}")
def snapshot(filename: str):
    return _serve(get_settings().snapshots_dir, filename)
