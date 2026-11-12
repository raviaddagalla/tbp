"""Remove demo/sim cameras and their data, and reset uploaded-footage cams.

Run with the backend STOPPED:
    python -m scripts.cleanup_demo_cameras
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Camera, CameraAdjacency, Tracklet  # noqa: E402
from app.services.vectorstore.factory import get_vector_store  # noqa: E402

DELETE_PATTERNS = ("sim://", "usb://")


def main() -> None:
    db = SessionLocal()
    try:
        store = get_vector_store()
        cams = db.query(Camera).all()
        to_delete = [c for c in cams if (c.rtsp_url or "").startswith(DELETE_PATTERNS)]
        keep = [c for c in cams if c not in to_delete]

        for cam in to_delete:
            print(f"Removing camera {cam.id} '{cam.name}' ({cam.rtsp_url})")
            try:
                store.delete(filters={"camera_id": cam.id})
            except Exception as exc:  # noqa: BLE001
                print(f"  vector rows for cam {cam.id}: {exc}")
            db.query(CameraAdjacency).filter(
                (CameraAdjacency.from_camera_id == cam.id) | (CameraAdjacency.to_camera_id == cam.id)
            ).delete(synchronize_session=False)
            db.query(Tracklet).filter(Tracklet.camera_id == cam.id).delete(synchronize_session=False)
            db.delete(cam)

        # Uploaded-footage cams: reset counters + wipe rows so the fixed
        # file reader can re-index from a clean slate.
        for cam in keep:
            if (cam.rtsp_url or "").startswith("file://"):
                print(f"Resetting camera {cam.id} '{cam.name}' for clean re-index")
                try:
                    store.delete(filters={"camera_id": cam.id})
                except Exception as exc:  # noqa: BLE001
                    print(f"  vector rows for cam {cam.id}: {exc}")
                cam.frames_indexed = 0
                cam.status = "offline"
                db.add(cam)

        db.commit()

        # Drop orphan upload files no camera points at any more.
        from app.core.config import get_settings

        uploads = get_settings().video_uploads_dir
        referenced = {(c.rtsp_url or "").replace("file://", "") for c in db.query(Camera).all()}
        for f in uploads.iterdir() if uploads.exists() else []:
            if f.is_file() and str(f) not in referenced:
                print(f"Removing orphan upload {f.name}")
                f.unlink(missing_ok=True)

        print(f"Done. {len(to_delete)} demo camera(s) removed; {len(keep)} kept.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
