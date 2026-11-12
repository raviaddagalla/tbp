"""Paragraph/section-aware text chunking with overlap."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.documents.parser import PageText


@dataclass
class Chunk:
    text: str
    page: int
    section: str
    index: int


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.replace("\r", "").split("\n\n")]
    out = []
    for p in paragraphs:
        for line in p.split("\n"):
            line = line.strip()
            if line:
                out.append(line)
    return out


def chunk_pages(pages: list[PageText], chunk_size: int = 700, overlap: int = 140) -> list[Chunk]:
    chunks: list[Chunk] = []
    current = ""
    current_page = 1
    section_of_first = ""  # section of the first content currently in `current`
    fallback_section = ""

    def add_to_current(text: str, page: int, section: str) -> None:
        nonlocal current, current_page, section_of_first
        stripped = current.strip()
        if not stripped or len(stripped) <= overlap:  # fresh or only an overlap tail
            current_page = page
            section_of_first = section
        current += ("" if not stripped else "\n") + text

    def flush(final: bool = False) -> None:
        nonlocal current
        text = current.strip()
        if text:
            chunks.append(
                Chunk(text=text, page=current_page, section=section_of_first or fallback_section, index=len(chunks))
            )
        if not final and overlap and text:
            current = text[-overlap:] + "\n"  # overlap tail keeps page/section of origin
        else:
            current = ""

    for page in pages:
        if page.heading:
            fallback_section = page.heading
        for para in _split_paragraphs(page.text):
            if len(current) + len(para) > chunk_size and current.strip():
                flush()
            if len(para) > chunk_size * 1.5:  # oversized paragraph: hard-split
                rest = para
                while len(rest) > chunk_size:
                    add_to_current(rest[:chunk_size], page.page, page.heading or fallback_section)
                    flush()
                    rest = rest[chunk_size:]
                add_to_current(rest, page.page, page.heading or fallback_section)
            else:
                add_to_current(para, page.page, page.heading or fallback_section)
    flush(final=True)
    return chunks
