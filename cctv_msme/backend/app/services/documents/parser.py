"""Document parsing: PDF / DOCX / images / text.

- PDFs: pdfplumber for text; if a page yields almost no text it is
  treated as scanned and OCR'd (PyMuPDF renders the page, pytesseract
  reads it). If OCR is unavailable the page is skipped with a clear note.
- DOCX: python-docx paragraphs + heading style as section marker.
- Images: OCR directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.services.documents import ocr as ocr_service

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40


@dataclass
class PageText:
    page: int
    text: str
    heading: str = ""


def parse_pdf(path: Path) -> tuple[list[PageText], bool]:
    """Returns (pages, ocr_used)."""
    ocr_used = False
    pages: list[PageText] = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                if len(text) < MIN_TEXT_CHARS:
                    # Likely a scanned page -> OCR
                    text = _ocr_pdf_page(path, i)
                    if text.strip():
                        ocr_used = True
                pages.append(PageText(page=i, text=text))
        return pages, ocr_used
    except ImportError:
        logger.error("pdfplumber not installed; cannot parse PDFs")
        raise RuntimeError("PDF parsing unavailable: pdfplumber not installed")


def _ocr_pdf_page(pdf_path: Path, page_no: int) -> str:
    if not ocr_service.is_ocr_available():
        logger.warning("OCR unavailable; scanned page %d of %s skipped", page_no, pdf_path.name)
        return ""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        page = doc.load_page(page_no - 1)
        pix = page.get_pixmap(dpi=200)
        from PIL import Image

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return ocr_service.ocr_image(img).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR of page %d failed: %s", page_no, exc)
        return ""


def parse_docx(path: Path) -> tuple[list[PageText], bool]:
    import docx

    doc = docx.Document(str(path))
    pages: list[PageText] = []
    buf: list[str] = []
    heading = ""
    word_count = 0
    page = 1

    def flush():
        nonlocal buf, page, heading
        if buf:
            pages.append(PageText(page=page, text="\n".join(buf), heading=heading))
            buf = []

    for para in doc.paragraphs:
        style = (para.style.name or "").lower()
        text = para.text.strip()
        if not text:
            flush()
            continue
        if "heading" in style:
            flush()
            heading = text
        else:
            buf.append(text)
            word_count += len(text.split())
        if word_count > 350:  # rough pagination for chunk metadata
            flush()
            page += 1
            word_count = 0
    flush()
    if not pages:
        pages = [PageText(page=1, text="(no text content found)")]
    return pages, False


def parse_image(path: Path) -> tuple[list[PageText], bool]:
    if not ocr_service.is_ocr_available():
        raise RuntimeError("OCR unavailable (Tesseract not found). Set TESSERACT_CMD or install Tesseract.")
    text = ocr_service.ocr_image_path(path)
    return [PageText(page=1, text=text)], True


def parse_text(path: Path) -> tuple[list[PageText], bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pages = [PageText(page=1, text=text)]
    return pages, False


def parse_file(path: Path, doc_type: str) -> tuple[list[PageText], bool]:
    if doc_type == "pdf":
        return parse_pdf(path)
    if doc_type == "docx":
        return parse_docx(path)
    if doc_type == "image":
        return parse_image(path)
    return parse_text(path)
