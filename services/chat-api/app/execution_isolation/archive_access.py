"""Open task audit ZIPs without retaining the full archive in memory."""

from __future__ import annotations

import tempfile
import zipfile
from contextlib import contextmanager
from typing import Iterator

from app.utils.oss_uploader import AliyunOSSUploader


MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@contextmanager
def open_audit_archive(object_path: str) -> Iterator[zipfile.ZipFile]:
    storage = AliyunOSSUploader()
    if storage.storage_backend == "local":
        with zipfile.ZipFile(storage.local_file_path(object_path)) as archive:
            yield archive
        return

    with tempfile.SpooledTemporaryFile(max_size=8 * CHUNK_BYTES) as spool:
        assert storage.bucket is not None
        source = storage.bucket.get_object(object_path)
        total = 0
        try:
            while chunk := source.read(CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Audit archive exceeds the read limit")
                spool.write(chunk)
        finally:
            source.close()
        spool.seek(0)
        with zipfile.ZipFile(spool) as archive:
            yield archive
