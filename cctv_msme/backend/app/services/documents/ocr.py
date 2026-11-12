"""OCR with graceful degradation (pytesseract + Tesseract binary)."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_available: bool | None = None


def is_ocr_available() -> bool:
    global _available
    if _available is not None:
        return _available
    try:
        import pytesseract

        cfg = get_settings()
        if cfg.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
        else:
            resolved = shutil.which("tesseract")
            if not resolved:
                _available = False
                logger.warning(
                    "Tesseract OCR binary not found on PATH. Scanned documents will be "
                    "marked as failed unless TESSERACT_CMD is set."
                )
                return False
            pytesseract.pytesseract.tesseract_cmd = resolved
        _available = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR unavailable: %s", exc)
        _available = False
    return _available


def ocr_image(image: Image.Image, lang: str = "eng") -> str:
    import pytesseract

    cfg = get_settings()
    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
    return pytesseract.image_to_string(image.convert("L"), lang=lang)


def ocr_image_path(path: Path, lang: str = "eng") -> str:
    with Image.open(path) as img:
        return ocr_image(img, lang=lang)
