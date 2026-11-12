"""Camera frame sources.

- RTSPCameraSource: real CCTV via OpenCV (cv2.VideoCapture + FFmpeg).
- VideoFileSource: uploaded CCTV footage files (file:// URLs). Reads frames
  once through; `finished` goes True at EOF so the worker exits cleanly.
- SimulatedCameraSource: procedural synthetic factory scenes so the whole
  pipeline can run with zero hardware. Registered by URLs like
  sim://loading_dock. Real RTSP URLs and sim:// URLs share the same worker
  code path.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

SCENES = ("loading_dock", "storage", "machine_zone", "office", "packaging")


class CameraSource(ABC):
    @abstractmethod
    def open(self) -> bool: ...

    @abstractmethod
    def read(self) -> tuple[bool, np.ndarray | None]:
        """Return (ok, frame_bgr). ok=False signals drop/timeout."""

    @abstractmethod
    def release(self) -> None: ...

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]: ...

    @property
    def fps(self) -> float:
        """Native frame rate; 0.0 for live sources (wall-clock pacing)."""
        return 0.0

    @property
    def finished(self) -> bool:
        """True when a finite source (e.g. uploaded file) has been fully read."""
        return False


def source_for(url: str, name: str) -> CameraSource:
    if url.startswith("sim://"):
        scene = url[len("sim://") :].strip("/") or "loading_dock"
        if scene not in SCENES:
            scene = "loading_dock"
        return SimulatedCameraSource(scene, name)
    if url.startswith("file://"):
        return VideoFileSource(url[len("file://") :], name)
    if url.startswith("usb://"):
        return USBCameraSource(url[len("usb://") :].strip("/") or "0", name)
    return RTSPCameraSource(url, name)


# ---------------------------------------------------------------------------
class USBCameraSource(CameraSource):
    """Local camera attached to this machine: webcams and external USB
    cameras. URLs are usb://<index> (e.g. usb://0 = first camera)."""

    def __init__(self, index: str, name: str):
        try:
            self.index = int(index)
        except ValueError:
            raise ValueError(f"Invalid USB camera index '{index}' (expected usb://0, usb://1, ...)") from None
        self.name = name
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        try:
            # CAP_DSHOW is the reliable backend for USB/webcams on Windows;
            # falls back to the default backend elsewhere.
            self._cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                self._cap.release()
                self._cap = cv2.VideoCapture(self.index)
            if not self._cap.isOpened():
                self.release()
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] usb open failed: %s", self.name, exc)
            self.release()
            return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None or not self._cap.isOpened():
            return False, None
        try:
            ok, frame = self._cap.read()
            if not ok or frame is None or frame.size == 0:
                return False, None
            return True, frame
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] usb read error: %s", self.name, exc)
            return False, None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    @property
    def size(self) -> tuple[int, int]:
        if self._cap is not None:
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if w > 0 and h > 0:
                return (w, h)
        return (960, 540)


# ---------------------------------------------------------------------------
class RTSPCameraSource(CameraSource):
    def __init__(self, url: str, name: str):
        self.url = url
        self.name = name
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        try:
            self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            for prop, val in (
                (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000),
                (cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000),
                (cv2.CAP_PROP_RTSP_TRANSPORT, 0),  # TCP
            ):
                try:
                    self._cap.set(prop, val)
                except Exception:  # noqa: BLE001 - property not supported
                    pass
            if not self._cap.isOpened():
                self.release()
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] open failed: %s", self.name, exc)
            self.release()
            return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None or not self._cap.isOpened():
            return False, None
        try:
            ok, frame = self._cap.read()
            if not ok or frame is None or frame.size == 0:
                return False, None
            return True, frame
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] read error: %s", self.name, exc)
            return False, None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    @property
    def size(self) -> tuple[int, int]:
        return (960, 540)


# ---------------------------------------------------------------------------
class VideoFileSource(CameraSource):
    """Reads an uploaded video file (CCTV footage) once through via FFmpeg.

    Robustness: a single transient decode hiccup on a large file must NOT be
    treated as the end of the video. `read()` retries a few times after
    seeking back a short distance, and only reports `finished` when the
    position is genuinely at (or past) the reported duration, or after
    repeated failures with no forward progress.
    """

    # Seconds of tolerance when comparing position against CAP_PROP duration.
    _EOF_EPSILON = 0.5
    # How far back to seek after a transient read failure.
    _TRANSIENT_SEEK_BACK = 2.0
    # Consecutive failures with no forward progress before giving up.
    _MAX_STALLED_READS = 5

    def __init__(self, path: str, name: str):
        self.path = str(Path(path).resolve())
        self.name = name
        self._cap: cv2.VideoCapture | None = None
        self._finished = False
        self._frames_read = 0
        self._stalled_reads = 0

    def open(self) -> bool:
        if not Path(self.path).is_file():
            # The file may have been uploaded from another laptop; pull a
            # local copy from the shared bucket before giving up.
            try:
                from app.services.media_storage import media_local_path

                local = media_local_path(f"uploads/videos/{Path(self.path).name}")
                if local is not None:
                    self.path = str(local)
            except Exception:  # noqa: BLE001 - fall through to "not found"
                pass
        if not Path(self.path).is_file():
            logger.warning("[%s] file not found: %s", self.name, self.path)
            return False
        try:
            self._cap = cv2.VideoCapture(self.path, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                self.release()
                return False
            # A fresh handle must NOT inherit a stale EOF flag from a
            # previous pass: reset it here or one transient failure would
            # make every later reopen report "file finished" instantly.
            self._finished = False
            self._stalled_reads = 0
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] open failed: %s", self.name, exc)
            self.release()
            return False

    def _at_eof(self) -> bool:
        """True when the current position is at (or past) the media end."""
        dur = self.duration_seconds
        if dur <= 0:
            return False  # unknown duration: fall back to retry logic
        return self.position_seconds >= dur - self._EOF_EPSILON

    def _seek_back(self, seconds: float) -> bool:
        if self._cap is None:
            return False
        try:
            target = max(0.0, self.position_seconds - seconds) * 1000.0
            self._cap.set(cv2.CAP_PROP_POS_MSEC, target)
            return True
        except Exception:  # noqa: BLE001 - seek is best-effort
            return False

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._finished:
            return False, None
        if self._cap is None or not self._cap.isOpened():
            return False, None
        try:
            ok, frame = self._cap.read()
            if ok and frame is not None and frame.size > 0:
                self._frames_read += 1
                self._stalled_reads = 0
                return True, frame

            # Transient failure or true EOF? If we are nowhere near the end
            # of the file, seek back a little and retry before giving up.
            if not self._at_eof():
                logger.warning("[%s] transient read failure at %.1fs; retrying", self.name, self.position_seconds)
                self._seek_back(self._TRANSIENT_SEEK_BACK)
                self._stalled_reads += 1
                if self._stalled_reads >= self._MAX_STALLED_READS:
                    logger.error(
                        "[%s] %d consecutive read failures without progress; giving up at %.1fs",
                        self.name,
                        self._stalled_reads,
                        self.position_seconds,
                    )
                    self._finished = True
                return False, None

            self._finished = True
            return False, None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] read error: %s (retrying)", self.name, exc)
            self._seek_back(self._TRANSIENT_SEEK_BACK)
            self._stalled_reads += 1
            if self._stalled_reads >= self._MAX_STALLED_READS:
                logger.error(
                    "[%s] read keeps failing; giving up at %.1fs",
                    self.name,
                    self.position_seconds,
                )
                self._finished = True
            return False, None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    def seek_seconds(self, seconds: float) -> None:
        """Jump to an absolute video position (used for resume/reconnect)."""
        if self._cap is not None:
            try:
                self._cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(seconds)) * 1000.0)
            except Exception:  # noqa: BLE001 - best-effort
                pass

    @property
    def size(self) -> tuple[int, int]:
        if self._cap is not None:
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if w > 0 and h > 0:
                return (w, h)
        return (960, 540)

    @property
    def fps(self) -> float:
        if self._cap is not None:
            fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0)
            if fps > 0:
                return fps
        return 25.0

    @property
    def duration_seconds(self) -> float:
        """Reported media duration in seconds; 0.0 when unknown."""
        if self._cap is not None:
            try:
                fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0)
                count = float(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if fps > 0 and count > 0:
                    return count / fps
            except Exception:  # noqa: BLE001
                pass
        return 0.0

    @property
    def position_seconds(self) -> float:
        """Current playback position in the file (video time)."""
        if self._cap is not None:
            try:
                t = float(self._cap.get(cv2.CAP_PROP_POS_MSEC) or 0)
                if t > 0:
                    return t / 1000.0
            except Exception:  # noqa: BLE001 - codec may not expose POS_MSEC
                pass
        return self._frames_read / self.fps

    @property
    def finished(self) -> bool:
        return self._finished


# ---------------------------------------------------------------------------
class SimulatedCameraSource(CameraSource):
    """Procedural scenes. Draws recognizable shapes (forklift, person, racks)
    so CLIP similarity search is meaningful in demos with no real cameras."""

    W, H = 960, 540

    def __init__(self, scene: str, name: str):
        self.scene = scene
        self.name = name
        self.t0 = time.time()
        self._rng = np.random.default_rng(abs(hash(scene)) % (2**32))
        self._palette = self._rng.integers(0, 255, size=(16, 3)).astype(int)

    def open(self) -> bool:
        return True

    def _rand_color(self, seed: int) -> tuple[int, int, int]:
        c = self._palette[seed % len(self._palette)]
        return int(c[0]), int(c[1]), int(c[2])

    def _draw_floor(self, img: np.ndarray) -> None:
        cv2.rectangle(img, (0, int(self.H * 0.55)), (self.W, self.H), (70, 74, 82), -1)
        for i in range(0, self.W, 80):
            cv2.line(img, (i, int(self.H * 0.55)), (i, self.H), (60, 64, 72), 2)
        cv2.line(img, (0, int(self.H * 0.55)), (self.W, int(self.H * 0.55)), (45, 48, 55), 6)

    def _draw_racks(self, img: np.ndarray, x0: int, y0: int, h: int, color) -> None:
        for row in range(3):
            for col in range(4):
                x = x0 + col * 70
                y = y0 + row * (h // 3 + 8)
                cv2.rectangle(img, (x, y), (x + 56, y + h // 3), color, -1)
                cv2.rectangle(img, (x, y), (x + 56, y + h // 3), (30, 32, 38), 2)

    def _draw_forklift(self, img: np.ndarray, x: int, y: int, carrying: bool = False) -> None:
        cv2.rectangle(img, (x, y), (x + 110, y + 55), (0, 40, 160), -1)
        cv2.rectangle(img, (x + 55, y - 25), (x + 105, y), (160, 20, 20), -1)
        cv2.rectangle(img, (x + 60, y - 25), (x + 105, y), (190, 190, 190), 2)
        if carrying:
            cv2.rectangle(img, (x - 8, y - 62), (x + 40, y - 30), (120, 80, 30), -1)
        cv2.rectangle(img, (x + 8, y + 50), (x + 30, y + 78), (20, 20, 22), -1)
        cv2.rectangle(img, (x + 78, y + 50), (x + 100, y + 78), (20, 20, 22), -1)
        cv2.circle(img, (x + 20, y + 84), 10, (18, 18, 20), -1)
        cv2.circle(img, (x + 88, y + 84), 10, (18, 18, 20), -1)

    def _draw_person(self, img: np.ndarray, x: int, y: int, color, helmet: bool = False) -> None:
        cv2.circle(img, (x, y - 26), 12, color, -1)
        if helmet:
            cv2.circle(img, (x, y - 30), 9, (220, 200, 40), -1)
        cv2.line(img, (x, y - 12), (x, y + 26), color, 10)
        cv2.line(img, (x, y), (x - 14, y + 26), color, 7)
        cv2.line(img, (x, y), (x + 14, y + 26), color, 7)
        cv2.line(img, (x, y + 26), (x, y + 46), color, 9)

    def _draw_machine(self, img: np.ndarray, x: int, y: int, spin_angle: int) -> None:
        cv2.rectangle(img, (x, y), (x + 220, y + 200), (90, 95, 105), -1)
        cv2.rectangle(img, (x + 10, y + 10), (x + 80, y + 60), (30, 34, 42), -1)
        cx, cy = x + 170, y + 90
        cv2.circle(img, (cx, cy), 45, (55, 60, 70), -1)
        for i in range(6):
            a = np.deg2rad(i * 60 + spin_angle)
            cv2.line(img, (cx, cy), (int(cx + 40 * np.cos(a)), int(cy + 40 * np.sin(a))), (160, 170, 180), 4)
        cv2.circle(img, (cx, cy), 12, (200, 120, 40), -1)
        cv2.rectangle(img, (x, y + 170), (x + 220, y + 200), (50, 55, 62), -1)

    def read(self) -> tuple[bool, np.ndarray | None]:
        t = time.time() - self.t0
        img = np.zeros((self.H, self.W, 3), dtype=np.uint8)
        cv2.rectangle(img, (0, 0), (self.W, self.H), (140, 148, 160), -1)  # wall
        self._draw_floor(img)

        if self.scene == "loading_dock":
            cv2.rectangle(img, (30, 80), (300, 250), (110, 115, 125), -1)  # dock door
            cv2.rectangle(img, (30, 80), (300, 250), (60, 64, 72), 4)
            f_x = int(250 + 380 * (0.5 + 0.5 * np.sin(t * 0.35)))
            self._draw_forklift(img, f_x, 360, carrying=(int(t) % 3 != 0))
            p_x = int(600 + 200 * (0.5 + 0.5 * np.sin(t * 0.5 + 2)))
            self._draw_person(img, p_x, 420, (0, 120, 200), helmet=True)
        elif self.scene == "storage":
            self._draw_racks(img, 60, 300, 140, (95, 70, 40))
            self._draw_racks(img, 480, 300, 140, (80, 60, 90))
            self._draw_racks(img, 640, 130, 110, (95, 70, 40))
            f_x = int(140 + 560 * (0.5 + 0.5 * np.sin(t * 0.3 + 1)))
            self._draw_forklift(img, f_x, 400)
            p_x = int(380 + 160 * np.sin(t * 0.7))
            self._draw_person(img, p_x, 300, (0, 120, 200), helmet=False)
        elif self.scene == "machine_zone":
            self._draw_machine(img, 120, 120, int(t * 40) % 360)
            self._draw_machine(img, 620, 140, int(-t * 30) % 360)
            p_x = int(500 + 260 * np.sin(t * 0.45))
            self._draw_person(img, p_x, 430, (0, 120, 200), helmet=True)
            if int(t * 2) % 5 == 0:  # occasional steam puffs
                cv2.circle(img, (180, 90), 25, (220, 220, 220), -1)
        elif self.scene == "office":
            for i, (dx, dy, cc) in enumerate([(60, 330, (110, 90, 60)), (380, 330, (110, 90, 60)), (700, 330, (110, 90, 60))]):
                cv2.rectangle(img, (dx, dy), (dx + 160, dy + 120), cc, -1)
                cv2.rectangle(img, (dx + 20, dy + 25), (dx + 140, dy + 110), (160, 200, 220), -1)
                cv2.rectangle(img, (dx + 55, dy + 60), (dx + 105, dy + 115), (60, 65, 75), -1)
                if cc == (110, 90, 60):
                    self._draw_person(img, dx + 80, dy + 40, (0, 120, 200), helmet=False)
        else:  # packaging
            cv2.rectangle(img, (150, 300), (400, 450), (150, 120, 60), -1)
            cv2.rectangle(img, (550, 300), (800, 450), (150, 120, 60), -1)
            f_x = int(200 + 400 * (0.5 + 0.5 * np.sin(t * 0.4 + 3)))
            self._draw_forklift(img, f_x, 380, carrying=True)
            p_x = int(700 + 150 * np.sin(t * 0.6))
            self._draw_person(img, p_x, 330, (0, 120, 200), helmet=True)

        return True, img

    def release(self) -> None:
        pass

    @property
    def size(self) -> tuple[int, int]:
        return (self.W, self.H)
