"""Durable, tenant-scoped DSH plugin tarballs."""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Any

from motor.motor_asyncio import AsyncIOMotorGridFSBucket

BUCKET_NAME = "dsh_plugin_archives"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


async def save_archive(db: Any, content: bytes, *, main_id: str) -> tuple[str, str]:
    if not content or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("Plugin archive exceeds the 100 MiB limit")
    digest = hashlib.sha256(content).hexdigest()
    archive_id = uuid.uuid4().hex
    await AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET_NAME).upload_from_stream_with_id(
        archive_id, f"{digest}.tgz", io.BytesIO(content),
        metadata={"main_id": main_id, "digest": digest},
    )
    return archive_id, digest


async def delete_archive(db: Any, archive_id: str) -> None:
    if archive_id:
        await AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET_NAME).delete(archive_id)
