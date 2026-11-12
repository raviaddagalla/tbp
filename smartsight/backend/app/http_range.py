"""HTTP Range file responses so <video> seeking works reliably.

Starlette's FileResponse range support varies by version, so SmartSight
implements the single-range case explicitly: browsers can then seek to the
exact timestamp of a search hit inside a large uploaded file.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _iter_file(path: Path, start: int, length: int, chunk_size: int = 256 * 1024):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def range_file_response(path: Path, request: Request, media_type: str | None = None, filename: str | None = None):
    media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    headers = {"Accept-Ranges": "bytes"}

    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if match:
            start_raw, end_raw = match.groups()
            if not start_raw and end_raw:
                # Suffix range: "bytes=-N" means the last N bytes.
                suffix = min(int(end_raw), file_size)
                start = file_size - suffix
                end = file_size - 1
            else:
                start = int(start_raw) if start_raw else 0
                end = int(end_raw) if end_raw else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                return StreamingResponse(
                    iter(()),
                    status_code=416,
                    headers={**headers, "Content-Range": f"bytes */{file_size}"},
                )
            length = end - start + 1
            return StreamingResponse(
                _iter_file(path, start, length),
                status_code=206,
                media_type=media_type,
                headers={
                    **headers,
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                    "Cache-Control": "no-store",
                },
            )

    if filename:
        return FileResponse(path, media_type=media_type, filename=filename, headers=headers)
    return FileResponse(path, media_type=media_type, headers={**headers, "Content-Length": str(file_size)})
