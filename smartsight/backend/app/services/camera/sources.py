"""Camera frame sources.

ESP32-CAM firmware families differ, so SmartSight does not assume RTSP:

* `ESP32CameraWebServer` sketch -> MJPEG at  http://<ip>/stream   (port 80 or 81)
* snapshot-only builds          -> JPEG  at  http://<ip>/capture
* RTSP bridges                  -> rtsp://...  (explicitly configured only)
* no hardware available         -> sim://demo  (clearly labelled demo scene)

`probe_stream()` tries the common endpoints and reports which ones actually
return video, with a preview frame so the user can confirm before saving.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import requests

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_BUFFER_BYTES = 4 * 1024 * 1024
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


@dataclass
class ProbeResult:
    ok: bool
    endpoint: str = ""
    kind: str = ""  # mjpeg | snapshot | rtsp | simulated
    detail: str = ""
    width: int = 0
    height: int = 0
    preview_data_url: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "endpoint": self.endpoint,
            "kind": self.kind,
            "detail": self.detail,
            "width": self.width,
            "height": self.height,
            "preview_data_url": self.preview_data_url,
        }


def _preview_data_url(frame_bgr: np.ndarray) -> str:
    preview = frame_bgr
    if preview.shape[1] > 480:
        scale = 480 / preview.shape[1]
        preview = cv2.resize(preview, (480, int(preview.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


def _candidate_urls(raw: str) -> list[str]:
    """Turn an IP/host or URL into plausible ESP32-CAM endpoints to probe."""
    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith(("sim://", "rtsp://", "rtmp://")):
        return [value]

    norm = value if "://" in value else f"http://{value}"
    from urllib.parse import urlparse
    parsed = urlparse(norm)
    host = parsed.hostname or value
    port = parsed.port
    path = (parsed.path or "").rstrip("/")

    candidates: list[str] = []

    # If the user gave an explicit stream/capture endpoint, only probe that exact URL
    if path.endswith(("/stream", "/capture", "/mjpeg")):
        return [norm]

    candidates: list[str] = []

    # If the user provided http:// or https:// with a host, include the exact URL first
    if value.startswith(("http://", "https://")):
        candidates.append(norm)

    if port:
        candidates.append(f"http://{host}:{port}/stream")
        candidates.append(f"http://{host}:{port}/capture")
    else:
        candidates.append(f"http://{host}/stream")
        candidates.append(f"http://{host}:81/stream")
        candidates.append(f"http://{host}/capture")
        candidates.append(f"http://{host}:81/capture")
        candidates.append(f"http://{host}/mjpeg")

    if norm not in candidates:
        candidates.append(norm)

    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _first_jpeg(chunks, max_bytes: int = 2 * 1024 * 1024):
    """Scan a byte-chunk iterator for the first complete JPEG."""
    buffer = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        start = buffer.find(JPEG_SOI)
        if start >= 0:
            end = buffer.find(JPEG_EOI, start + 2)
            if end >= 0:
                return bytes(buffer[start : end + 2])
        if len(buffer) > max_bytes:
            return None
    return None


def probe_stream(raw: str, timeout: float | None = None) -> ProbeResult:
    """Probe a URL/host and return the first endpoint that yields real frames."""
    settings = get_settings()
    timeout = timeout or min(8.0, settings.camera_connect_timeout + 2)
    last_error = "No camera endpoints responded"
    for url in _candidate_urls(raw):
        if url.startswith("sim://"):
            from app.services.camera.simulated import SimulatedSource

            source = SimulatedSource(url)
            ok, frame = source.read()
            if ok and frame is not None:
                return ProbeResult(True, url, "simulated", "Built-in simulated demo scene", frame.shape[1], frame.shape[0], _preview_data_url(frame))
            return ProbeResult(False, url, "simulated", "Simulated source unavailable", detail=last_error)
        if url.startswith(("rtsp://", "rtmp://")):
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            try:
                if cap.isOpened():
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        return ProbeResult(
                            True, url, "rtsp", "RTSP stream responded", frame.shape[1], frame.shape[0], _preview_data_url(frame)
                        )
                last_error = f"{url}: RTSP stream did not respond"
            finally:
                cap.release()
            continue

        try:
            response = requests.get(url, stream=True, timeout=(min(4.0, timeout), timeout))
            content_type = (response.headers.get("content-type") or "").lower()
            if response.status_code >= 400:
                last_error = f"{url}: HTTP {response.status_code}"
                response.close()
                continue
            if "text/html" in content_type:
                last_error = f"{url}: HTML page returned, not camera stream"
                response.close()
                continue
            if "image/jpeg" in content_type:
                data = response.raw.read(1024 * 1024, decode_content=True) or b""
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    return ProbeResult(
                        True, url, "snapshot", "JPEG snapshot endpoint", frame.shape[1], frame.shape[0], _preview_data_url(frame)
                    )
                last_error = f"{url}: snapshot was not a decodable JPEG"
                continue
            # MJPEG (or unknown multipart type): look for a JPEG inside.
            jpeg = _first_jpeg(response.iter_content(chunk_size=8192), max_bytes=512 * 1024)
            if jpeg:
                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    kind = "mjpeg" if "multipart" in content_type else "mjpeg"
                    return ProbeResult(
                        True, url, kind, "MJPEG stream endpoint", frame.shape[1], frame.shape[0], _preview_data_url(frame)
                    )
            last_error = f"{url}: no JPEG frames in response ({content_type or 'unknown content type'})"
            response.close()
        except requests.RequestException as exc:
            last_error = f"{url}: {_network_error(exc)}"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{url}: {_network_error(exc)}"
    return ProbeResult(False, detail=last_error)


def _network_error(exc: Exception) -> str:
    """Short, actionable message instead of a multi-line requests traceback."""
    if isinstance(exc, requests.Timeout):
        return "timed out — check the IP address and that the board is on the same Wi-Fi network"
    if isinstance(exc, requests.ConnectionError):
        return "connection refused or host unreachable — check the IP address and port"
    text = str(exc).strip().splitlines()[0]
    return text[:200] or exc.__class__.__name__


class CameraSource:
    """Minimal interface shared by every source."""

    kind = "unknown"
    label = ""

    def open(self) -> bool: ...
    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def release(self) -> None: ...


class MjpegHttpSource(CameraSource):
    """Incremental MJPEG reader (no full response buffering)."""

    kind = "mjpeg"

    def __init__(self, url: str):
        self.url = url
        self.label = url
        self._response = None
        self._stream = None
        self._buffer = bytearray()
        self._last_chunk_at = 0.0

    def open(self) -> bool:
        settings = get_settings()
        try:
            self._response = requests.get(
                self.url,
                stream=True,
                timeout=(settings.camera_connect_timeout, settings.camera_read_timeout),
            )
            if self._response.status_code >= 400:
                self.release()
                return False
            content_type = (self._response.headers.get("content-type") or "").lower()
            if "image/jpeg" in content_type or "text/html" in content_type or "text/plain" in content_type:
                # The endpoint turned out to be snapshot-only or an HTML page.
                self.release()
                return False
            self._stream = self._response.iter_content(chunk_size=4096)
            self._buffer.clear()
            return True
        except requests.RequestException as exc:
            logger.warning("MJPEG open failed for %s: %s", self.url, exc)
            self.release()
            return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._stream is None:
            return False, None
        deadline = time.time() + get_settings().camera_read_timeout
        try:
            while time.time() < deadline:
                start = self._buffer.find(JPEG_SOI)
                if start >= 0:
                    end = self._buffer.find(JPEG_EOI, start + 2)
                    if end >= 0:
                        jpeg = bytes(self._buffer[start : end + 2])
                        del self._buffer[: end + 2]
                        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            return True, frame
                        continue
                if start > 0:
                    del self._buffer[:start]
                if len(self._buffer) > MAX_BUFFER_BYTES:
                    self._buffer.clear()
                chunk = next(self._stream, None)
                if chunk is None:
                    return False, None
                self._buffer.extend(chunk)
                self._last_chunk_at = time.time()
        except Exception as exc:  # noqa: BLE001 - network failure -> caller reconnects
            logger.warning("MJPEG read failed for %s: %s", self.url, exc)
            return False, None
        return False, None

    def release(self) -> None:
        try:
            if self._response is not None:
                self._response.close()
        except Exception:  # noqa: BLE001
            pass
        self._response = None
        self._stream = None
        self._buffer.clear()


class SnapshotHttpSource(CameraSource):
    """Repeated JPEG snapshot polling for snapshot-only ESP32 firmware."""

    kind = "snapshot"

    def __init__(self, url: str):
        self.url = url
        self.label = url

    def open(self) -> bool:
        return self.read()[0]

    def read(self) -> tuple[bool, np.ndarray | None]:
        settings = get_settings()
        try:
            response = requests.get(self.url, timeout=(settings.camera_connect_timeout, settings.camera_read_timeout))
            if response.status_code >= 400 or not response.content:
                return False, None
            frame = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
            return (True, frame) if frame is not None else (False, None)
        except requests.RequestException:
            return False, None

    def release(self) -> None:
        return None


class RTSPSource(CameraSource):
    """Explicit RTSP support (only when the user configures an rtsp:// URL)."""

    kind = "rtsp"

    def __init__(self, url: str):
        self.url = url
        self.label = url
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        try:
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        except Exception:  # noqa: BLE001 - property unsupported
            pass
        if not self._cap.isOpened():
            self.release()
            return False
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if not ok or frame is None or frame.size == 0:
            return False, None
        return True, frame

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
        self._cap = None


class DummyOfflineSource(CameraSource):
    """Source when no stream URL is configured or available."""

    kind = "none"

    def __init__(self, message: str = "No camera stream URL configured"):
        self.label = message

    def open(self) -> bool:
        return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        return False, None

    def release(self) -> None:
        pass


def build_source(url: str) -> CameraSource:
    """Resolve a configured URL into a concrete frame source."""
    value = (url or "").strip()
    if not value:
        return DummyOfflineSource("Enter an ESP32-CAM stream URL")
    if value.startswith("sim://"):
        from app.services.camera.simulated import SimulatedSource

        return SimulatedSource(value)
    if value.startswith(("rtsp://", "rtmp://")):
        return RTSPSource(value)

    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"

    lower = value.lower().rstrip("/")
    if lower.endswith("/capture"):
        return SnapshotHttpSource(value)
    if lower.endswith("/stream"):
        return MjpegHttpSource(value)

    # For generic host or base URL like http://10.63.89.95, probe candidate endpoints
    logger.info("Resolving camera endpoint for %s...", value)
    probe = probe_stream(value, timeout=2.5)
    if probe.ok and probe.endpoint:
        logger.info("Auto-resolved camera %s -> %s (%s)", value, probe.endpoint, probe.kind)
        if probe.kind == "mjpeg":
            return MjpegHttpSource(probe.endpoint)
        if probe.kind == "snapshot":
            return SnapshotHttpSource(probe.endpoint)
        if probe.kind == "rtsp":
            return RTSPSource(probe.endpoint)

    # If probe could not connect, check if port is unspecified -> standard port 81 /stream default
    from urllib.parse import urlparse
    parsed = urlparse(value)
    if not parsed.port and not (parsed.path or "").strip("/"):
        return MjpegHttpSource(f"http://{parsed.hostname}:81/stream")

    return MjpegHttpSource(value)


def demo_scene_available() -> bool:
    return Path(get_settings().demo_scene_path).is_file()
