"""ESP32-CAM endpoints: status, configuration, connection test, live stream."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.media import offline_jpeg
from app.schemas import CameraConfigUpdate, ProbeRequest
from app.services.camera.sources import probe_stream
from app.services.runtime import get_runtime
from app.services.overview import camera_row
from app.utils import to_iso, utcnow

router = APIRouter(prefix="/camera", tags=["camera"])

_BOUNDARY = "smartsightframe"


@router.get("/status")
def camera_status() -> dict:
    runtime = get_runtime()
    return {**runtime.camera.stats(), "config": camera_row()}


@router.post("/start")
def camera_start() -> dict:
    runtime = get_runtime()
    result = runtime.camera.start()
    return {**result, "status": runtime.camera.stats()}


@router.post("/stop")
def camera_stop() -> dict:
    runtime = get_runtime()
    result = runtime.camera.stop()
    return {**result, "status": runtime.camera.stats()}


@router.put("/config")
async def camera_config(body: CameraConfigUpdate) -> dict:
    runtime = get_runtime()
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return {"ok": True, "status": runtime.camera.stats()}

    if "stream_url" in updates and updates["stream_url"]:
        raw_url = updates["stream_url"].strip()
        if raw_url and not raw_url.startswith(("http://", "https://", "rtsp://", "rtmp://", "sim://")):
            raw_url = f"http://{raw_url}"
        updates["stream_url"] = raw_url

    was_running = runtime.camera.running
    needs_restart = was_running and any(
        key in updates for key in ("stream_url", "live_fps", "index_interval_seconds", "auto_start")
    )
    if needs_restart:
        await asyncio.to_thread(runtime.camera.stop)

    config = runtime.camera.update_config(**updates)

    if needs_restart:
        await asyncio.to_thread(runtime.camera.start)

    return {"ok": True, "config": config, "status": runtime.camera.stats()}


@router.post("/test")
async def camera_test(body: ProbeRequest | None = None) -> dict:
    configured = camera_row().get("stream_url", "")
    url = (body.stream_url if body and body.stream_url else configured) or ""
    if not url.strip():
        raise HTTPException(status_code=400, detail="Enter an ESP32-CAM IP address or stream URL")
    result = await asyncio.to_thread(probe_stream, url.strip())
    return result.as_dict()


@router.get("/stream")
async def camera_stream(request: Request, overlay: bool = Query(True)):
    """MJPEG preview of the latest processed frame (annotated or raw)."""
    runtime = get_runtime()

    async def generate():
        last_sent = 0.0
        last_stamp = -1.0
        while not await request.is_disconnected():
            jpeg, stamp = runtime.camera.preview_jpeg(overlay=overlay)
            now = time.time()
            if jpeg is None:
                jpeg = offline_jpeg()
                stamp = 0.0
            # Re-send only new frames, with a 1s keep-alive repeat.
            if stamp != last_stamp or now - last_sent > 1.0:
                last_stamp = stamp
                last_sent = now
                yield (
                    b"--" + _BOUNDARY.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
            await asyncio.sleep(0.12)

    return StreamingResponse(
        generate(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )


@router.get("/snapshot")
def camera_snapshot(overlay: bool = Query(True)):
    runtime = get_runtime()
    jpeg, _ = runtime.camera.preview_jpeg(overlay=overlay)
    if jpeg is None:
        jpeg = offline_jpeg()
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/snapshot")
def camera_capture(overlay: bool = Query(True)) -> dict:
    runtime = get_runtime()
    result = runtime.camera.capture_snapshot(overlay=overlay)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail", "No live frame available"))
    result["captured_at"] = to_iso(utcnow())
    return result


@router.get("/detections")
def camera_detections() -> dict:
    runtime = get_runtime()
    stats = runtime.camera.stats()
    return {
        "detections": runtime.camera.detections(),
        "captured_at": stats.get("last_frame_at", ""),
        "status": stats.get("status", "offline"),
        "source_kind": stats.get("source_kind", "none"),
        "source_label": stats.get("source_label", ""),
        "frame_width": stats.get("frame_width", 0),
        "frame_height": stats.get("frame_height", 0),
        "measured_fps": stats.get("measured_fps", 0),
    }
