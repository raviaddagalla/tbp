"""Media storage: local disk plus optional Cloudflare R2 mirror.

Local disk stays the primary cache; when MEDIA_REMOTE_ENABLED=1, every file
is also mirrored to an S3-compatible bucket (R2) so multiple laptops share
the same thumbnails/videos/clips. Reads fall back to the bucket when the
local copy is missing (e.g. a file uploaded by the other laptop).

Key layout mirrors the local data dir, relative to data_dir:
    thumbs/<name>.jpg
    clips/<camera_id>/<name>.mp4
    uploads/videos/<uuid>.mp4
    uploads/<doc_id>/<filename>
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def _client() -> Any:
    settings = get_settings()
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name=settings.r2_region or "auto",
    )


def _enabled() -> bool:
    s = get_settings()
    return bool(s.media_remote_enabled and s.r2_bucket and s.r2_endpoint_url and s.r2_access_key_id)


def _bucket() -> str:
    return get_settings().r2_bucket


def _local_path(rel_key: str) -> Path:
    # Keys are always stored POSIX-style (forward slashes).
    safe = rel_key.replace("\\", "/").lstrip("/")
    return (get_settings().data_dir / safe).resolve()


def media_put(rel_key: str, data: bytes) -> None:
    """Write bytes locally and mirror to R2 (best-effort)."""
    path = _local_path(rel_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        logger.warning("local media write failed (%s): %s", rel_key, exc)
    if _enabled():
        try:
            _client().put_object(Bucket=_bucket(), Key=rel_key, Body=data)
        except Exception as exc:  # noqa: BLE001 - remote mirror is best-effort
            logger.warning("R2 put failed (%s): %s", rel_key, exc)


def media_put_file(rel_key: str, local_file: Path) -> None:
    """Mirror an existing local file to R2 (streamed; best-effort)."""
    if _enabled() and local_file.is_file():
        try:
            _client().upload_file(str(local_file), _bucket(), rel_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("R2 upload failed (%s): %s", rel_key, exc)


def media_get(rel_key: str) -> bytes | None:
    """Fetch bytes: local first, then R2 (cached back to local disk)."""
    path = _local_path(rel_key)
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            pass
    if not _enabled():
        return None
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=rel_key)
        data = resp["Body"].read()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:
            pass
        return data
    except Exception as exc:  # noqa: BLE001 - key may not exist remotely either
        logger.debug("R2 get failed (%s): %s", rel_key, exc)
        return None


def media_local_path(rel_key: str) -> Path | None:
    """Return a local path for the key, downloading from R2 if needed."""
    path = _local_path(rel_key)
    if path.is_file():
        return path
    data = media_get(rel_key)
    if data is None:
        return None
    return path if path.is_file() else None


def media_delete(rel_key: str) -> None:
    """Remove a key locally and remotely (best-effort)."""
    path = _local_path(rel_key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    if _enabled():
        try:
            _client().delete_object(Bucket=_bucket(), Key=rel_key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("R2 delete failed (%s): %s", rel_key, exc)


def media_stream_r2(rel_key: str, range_header: str | None):
    """Stream a file from R2 with HTTP Range support.

    Returns a Starlette response, or None if the key is missing. Local files
    should use FileResponse instead (native Range support).
    """
    if not _enabled():
        return None
    try:
        kwargs: dict[str, Any] = {"Bucket": _bucket(), "Key": rel_key}
        if range_header and range_header.startswith("bytes="):
            kwargs["Range"] = range_header
        resp = _client().get_object(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("R2 stream open failed (%s): %s", rel_key, exc)
        return None

    from fastapi.responses import StreamingResponse

    status = 206 if "Range" in kwargs else 200
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": resp.get("ContentType") or "application/octet-stream",
        "Content-Length": str(resp.get("ContentLength") or 0),
    }
    cr = resp.get("ContentRange")
    if cr:
        headers["Content-Range"] = cr

    def gen():
        try:
            yield from resp["Body"].iter_chunks()
        finally:
            resp["Body"].close()

    return StreamingResponse(gen(), status_code=status, headers=headers)
