from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from fastapi import HTTPException, status
from starlette.responses import FileResponse, StreamingResponse

from app.services.knowledge_storage import StorageService


def parse_byte_range(value: str, size: int) -> tuple[int, int] | None:
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


def _iter_fileobj(fileobj: BinaryIO):
    try:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        close = getattr(fileobj, "close", None)
        if callable(close):
            close()


def _content_disposition(filename: str) -> str:
    safe = str(filename or "document").replace('"', "").replace("\r", "").replace("\n", "")
    ascii_name = "".join(character if ord(character) < 128 else "_" for character in safe) or "document"
    return f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe.encode("utf-8"))}'


def preview_response(
    *,
    storage: StorageService,
    storage_key: str,
    media_type: str,
    filename: str,
    range_header: str = "",
):
    if storage.storage_type == "local":
        fileobj = storage.open_file(storage_key)
        path = Path(str(getattr(fileobj, "name", "")))
        fileobj.close()
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type="inline",
        )
    return _oss_response(storage, storage_key, media_type, filename, range_header)


def _oss_response(
    storage: StorageService,
    storage_key: str,
    media_type: str,
    filename: str,
    range_header: str,
):
    try:
        bucket: Any = getattr(storage, "bucket")
        size = int(bucket.head_object(storage_key).content_length)
        try:
            byte_range = parse_byte_range(range_header, size)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="invalid byte range",
                headers={"Content-Range": f"bytes */{size}"},
            ) from exc
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": _content_disposition(filename),
        }
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
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预览文件不存在") from exc


__all__ = ["parse_byte_range", "preview_response"]
