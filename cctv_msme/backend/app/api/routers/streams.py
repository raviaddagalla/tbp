"""Streaming endpoints: MJPEG live preview, thumbnails, clip playback."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_query_token, require_media_scope, require_media_scope_for_camera
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Camera, User
from app.state import state
from app.utils.video import offline_placeholder_jpeg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["streams"])

_BOUNDARY = "frame"


@router.get("/preview/{camera_id}")
async def mjpeg_preview(
    camera_id: int,
    request: Request,
    user: User = Depends(get_current_user_query_token),
):
    """MJPEG stream served from the worker's latest-frame buffer.

    Browsers display it directly in <img> tags; no per-viewer RTSP session.
    """
    require_media_scope_for_camera(user, camera_id, f"/api/streams/preview/{camera_id}")
    if not state.worker_manager or camera_id not in state.worker_manager.latest_buffers:
        raise HTTPException(status_code=404, detail="Camera not active")

    buffer = state.worker_manager.latest_buffers[camera_id]

    async def gen():
        while not await request.is_disconnected():
            jpeg, _ = buffer.get()
            if not jpeg:
                jpeg = offline_placeholder_jpeg()
            yield (
                b"--" + _BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg)).encode()
                + b"\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/snapshot/{camera_id}")
async def snapshot(camera_id: int, user: User = Depends(get_current_user_query_token)):
    """Latest frame as a single JPEG."""
    require_media_scope_for_camera(user, camera_id, f"/api/streams/snapshot/{camera_id}")
    if not state.worker_manager or camera_id not in state.worker_manager.latest_buffers:
        raise HTTPException(status_code=404, detail="Camera not active")
    jpeg, _ = state.worker_manager.latest_buffers[camera_id].get()
    if not jpeg:
        jpeg = offline_placeholder_jpeg()
    return StreamingResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/thumb/{filename:path}")
async def thumbnail(filename: str, request: Request, user: User = Depends(get_current_user_query_token)):
    require_media_scope(user, f"/api/streams/thumb/{filename}")
    _check_thumb_zone(user, Path(filename).name)
    settings = get_settings()
    path = (settings.thumbs_dir / Path(filename).name).resolve()
    if settings.thumbs_dir.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    if path.exists():
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    # Not local (e.g. indexed on another laptop) -> try the shared bucket.
    from app.services.media_storage import media_get

    data = media_get(f"thumbs/{Path(filename).name}")
    if data is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/clip/{camera_id}/{segment_id}.mp4")
async def clip_playback(
    camera_id: int,
    segment_id: str,
    request: Request,
    user: User = Depends(get_current_user_query_token),
):
    """Playback a rolling segment. FileResponse supports HTTP Range (seeking)."""
    require_media_scope_for_camera(user, camera_id, f"/api/streams/clip/{camera_id}/{segment_id}.mp4")
    settings = get_settings()
    safe = Path(segment_id).name
    path = settings.clips_dir / str(camera_id) / f"{safe}.mp4"
    if path.exists():
        return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")
    # Segment may have been recorded on another laptop -> shared bucket.
    from app.services.media_storage import media_stream_r2

    resp = media_stream_r2(f"clips/{camera_id}/{safe}.mp4", request.headers.get("range"))
    if resp is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return resp


@router.get("/file/{camera_id}")
async def file_playback(
    camera_id: int,
    request: Request,
    user: User = Depends(get_current_user_query_token),
    db: Session = Depends(get_db),
):
    """Playback of an uploaded footage file (local FileResponse with HTTP
    Range, or streamed from the shared bucket when the file is not local)."""
    require_media_scope_for_camera(user, camera_id, f"/api/streams/file/{camera_id}")
    camera = db.get(Camera, camera_id)
    if not camera or not (camera.rtsp_url or "").startswith("file://"):
        raise HTTPException(status_code=404, detail="Camera is not an uploaded footage source")
    path = Path(camera.rtsp_url[len("file://") :]).resolve()
    if path.is_file():
        return FileResponse(path, media_type="video/mp4", filename=f"camera_{camera_id}.mp4")
    # Not on this laptop -> stream from the shared bucket (Range supported).
    from app.services.media_storage import media_stream_r2

    key = f"uploads/videos/{path.name}"
    resp = media_stream_r2(key, request.headers.get("range"))
    if resp is None:
        raise HTTPException(status_code=404, detail="Uploaded file no longer exists")
    return resp


@router.get("/file/{camera_id}/clip")
async def file_clip_playback(
    camera_id: int,
    start: float = 0.0,
    duration: float = 10.0,
    user: User = Depends(get_current_user_query_token),
    db: Session = Depends(get_db),
):
    """Playback of a short trimmed segment of an uploaded footage file.

    Browsers struggle to seek inside large MP4s whose moov atom sits at the
    end of the file (typical for downloaded footage), which makes them play
    from the start instead of the wanted moment. This endpoint cuts a small
    clip around the target timestamp (default 10s) with PyAV's bundled FFmpeg
    and serves that — fast to load and seek. Clips are cached on disk.
    """
    require_media_scope_for_camera(user, camera_id, f"/api/streams/file/{camera_id}/clip")
    camera = db.get(Camera, camera_id)
    if not camera or not (camera.rtsp_url or "").startswith("file://"):
        raise HTTPException(status_code=404, detail="Camera is not an uploaded footage source")
    src = Path(camera.rtsp_url[len("file://") :]).resolve()
    if not src.is_file():
        # Source lives on the shared bucket (uploaded from another laptop):
        # fetch a local copy first so PyAV can cut it.
        from app.services.media_storage import media_local_path

        remote = media_local_path(f"uploads/videos/{src.name}")
        if remote is None:
            raise HTTPException(status_code=404, detail="Uploaded file no longer exists")
        src = remote

    start = max(0.0, float(start))
    duration = min(30.0, max(1.0, float(duration)))
    settings = get_settings()
    out_dir = settings.clips_dir / str(camera_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"clip_{start:.2f}_{duration:.2f}.mp4"

    stale = not out.exists() or (src.stat().st_mtime > out.stat().st_mtime)
    if stale:
        try:
            await asyncio.to_thread(_cut_clip, src, out, start, duration)
        except Exception as exc:  # noqa: BLE001 - fall back to full file
            logger.warning("clip cut failed for cam %s at %.1fs: %s", camera_id, start, exc)
            return FileResponse(src, media_type="video/mp4", filename=f"camera_{camera_id}.mp4")
    if not out.exists():
        raise HTTPException(status_code=500, detail="Clip could not be generated")
    from app.services.media_storage import media_put_file

    media_put_file(f"clips/{camera_id}/{out.name}", out)
    return FileResponse(out, media_type="video/mp4", filename=f"camera_{camera_id}_clip.mp4")


def _cut_clip(src: Path, out: Path, start: float, duration: float) -> None:
    """Cut [start, start+duration) from the source into a small mp4.

    Fast path: packet-level stream copy (no re-encode, near-instant, starts at
    the nearest keyframe before the window). Fallback: full decode + libx264
    transcode when the source timestamps are too messy for a clean copy.
    """
    import av

    tmp = out.with_suffix(".tmp.mp4")
    try:
        _cut_clip_copy(av, src, tmp, start, duration)
    except Exception:  # noqa: BLE001 - fall back to transcode
        try:
            _cut_clip_transcode(av, src, tmp, start, duration)
        except Exception:
            raise
    if tmp.exists():
        tmp.replace(out)


def _cut_clip_copy(av, src: Path, out: Path, start: float, duration: float) -> None:
    from fractions import Fraction

    inp = av.open(str(src))
    try:
        vstream = next((s for s in inp.streams if s.type == "video"), None)
        if vstream is None:
            raise RuntimeError("no video stream")
        tb = vstream.time_base
        end_pts = int((start + duration) * tb.denominator / tb.numerator)
        # Seek to the keyframe just before the window.
        seek_pts = max(0, int((start - 1.0) * tb.denominator / tb.numerator))
        inp.seek(seek_pts, stream=vstream, backward=True, any_frame=False)

        out_c = av.open(str(out), mode="w", format="mp4", options={"movflags": "faststart"})
        try:
            out_stream = out_c.add_stream_from_template(vstream)
            base = None
            for packet in inp.demux(vstream):
                if packet.dts is None or packet.pts is None:
                    continue
                if packet.pts > end_pts:  # absolute pts: stop at window end
                    break
                if base is None:
                    base = packet.dts
                packet.dts -= base  # rebase so the clip starts at 0
                packet.pts -= base
                packet.stream = out_stream
                out_c.mux(packet)
        finally:
            out_c.close()
    finally:
        inp.close()


def _cut_clip_transcode(av, src: Path, out: Path, start: float, duration: float) -> None:
    from fractions import Fraction

    inp = av.open(str(src))
    try:
        vstream = next((s for s in inp.streams if s.type == "video"), None)
        if vstream is None:
            raise RuntimeError("no video stream")
        tb = vstream.time_base
        start_pts = int(start * tb.denominator / tb.numerator)
        end_pts = int((start + duration) * tb.denominator / tb.numerator)
        inp.seek(start_pts, stream=vstream, backward=True, any_frame=False)

        fps = float(vstream.average_rate or 25.0)
        fps_r = Fraction(int(round(fps))).limit_denominator(1000)
        out_c = av.open(str(out), mode="w", format="mp4", options={"movflags": "faststart"})
        try:
            enc = out_c.add_stream("libx264", rate=fps_r)
            enc.width = vstream.width
            enc.height = vstream.height
            enc.pix_fmt = "yuv420p"
            enc.options = {"preset": "veryfast", "crf": "26"}
            frame_n = 0
            for frame in inp.decode(vstream):
                if frame.pts is not None and frame.pts > end_pts:
                    break
                frame.pts = int(frame_n * fps_r.denominator / fps_r.numerator)
                for pkt in enc.encode(frame):
                    out_c.mux(pkt)
                frame_n += 1
            for pkt in enc.encode(None):
                out_c.mux(pkt)
        finally:
            out_c.close()
    finally:
        inp.close()


def _check_thumb_zone(user: User, thumb_name: str) -> None:
    """Thumbnails are named <camera_id>_<epoch>_<seq>.jpg — enforce zone."""
    if user.role not in ("worker", "supervisor") or not user.zone:
        return
    try:
        camera_id = int(thumb_name.split("_", 1)[0])
    except (ValueError, IndexError):
        return
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        cam = db.get(Camera, camera_id)
        if cam is None:
            from fastapi import HTTPException as _HE

            raise _HE(status_code=404, detail="Thumbnail not found")
        if cam.zone != user.zone:
            from fastapi import HTTPException as _HE

            raise _HE(status_code=403, detail="Thumbnail is outside your zone")
    finally:
        db.close()


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    cameras = db.query(Camera).all()
    return {
        "ready": state.ready,
        "cameras": len(cameras),
        "embedder_ready": bool(state.embedder),
        "vector_store": state.vector_store.name() if state.vector_store else None,
        "llm_provider": state.llm.provider if state.llm else None,
    }

