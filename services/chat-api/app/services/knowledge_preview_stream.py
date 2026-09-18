from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from fastapi import HTTPException, status
from starlette.responses import FileResponse, StreamingResponse

from app.core.config import get_settings


def _iter_fileobj(fileobj: BinaryIO):
    try:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            fileobj.close()
        except Exception:
            pass


def parse_byte_range(value: str, size: int) -> tuple[int, int] | None:
    """Parse one HTTP byte range. Multiple ranges are intentionally unsupported."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.startswith("bytes=") or "," in raw or size <= 0:
        raise ValueError("invalid range")
    start_text, separator, end_text = raw[6:].partition("-")
    if not separator:
        raise ValueError("invalid range")
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            raise ValueError("invalid range")
        return max(0, size - suffix), size - 1
    start = int(start_text)
    if start < 0 or start >= size:
        raise ValueError("range outside file")
    end = int(end_text) if end_text else size - 1
    if end < start:
        raise ValueError("invalid range")
    return start, min(end, size - 1)


def preview_response(
    *,
    document: dict[str, Any],
    storage_field: str,
    media_type: str,
    range_header: str = "",
):
    settings = get_settings()
    storage_key = str(document.get(storage_field) or "")
    if not storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="preview not ready")
    storage_type = str(document.get("storage_type") or settings.KNOWLEDGE_STORAGE_TYPE or "local").lower()
    if storage_type == "oss":
        return _oss_response(storage_key, media_type, range_header)
    return FileResponse(
        _local_path(storage_key),
        media_type=media_type,
        content_disposition_type="inline",
    )


def _local_path(storage_key: str) -> Path:
    root = Path(get_settings().KNOWLEDGE_LOCAL_STORAGE_DIR).expanduser().resolve()
    path = (root / storage_key.strip().lstrip("/").replace("\\", "/")).resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid file path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    return path


def _oss_response(storage_key: str, media_type: str, range_header: str):
    settings = get_settings()
    endpoint = settings.KNOWLEDGE_OSS_ENDPOINT or settings.OSS_ENDPOINT
    bucket_name = settings.KNOWLEDGE_OSS_BUCKET or settings.OSS_BUCKET_NAME
    try:
        import oss2  # type: ignore

        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        size = int(bucket.head_object(storage_key).content_length)
        try:
            byte_range = parse_byte_range(range_header, size)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="invalid byte range",
                headers={"Content-Range": f"bytes */{size}"},
            ) from exc
        headers = {"Accept-Ranges": "bytes"}
        response_status = status.HTTP_200_OK
        if byte_range:
            start, end = byte_range
            fileobj = bucket.get_object(storage_key, byte_range=(start, end))
            headers.update({
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            response_status = status.HTTP_206_PARTIAL_CONTENT
        else:
            fileobj = bucket.get_object(storage_key)
            headers["Content-Length"] = str(size)
        return StreamingResponse(
            _iter_fileobj(fileobj),
            media_type=media_type,
            status_code=response_status,
            headers=headers,
        )
    except HTTPException:
        raise
    except ImportError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="oss dependency missing") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc


__all__ = ["parse_byte_range", "preview_response"]
