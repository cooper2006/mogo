"""Dual-format Skill archives: legacy inline BSON and new GridFS files."""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from typing import Any

from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from .validator import MAX_ARCHIVE_BYTES


BUCKET_NAME = "skill_archives"


def _bucket(db: Any) -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET_NAME)


async def archive_fields(db: Any, content: bytes, *, main_id: str, digest: str) -> dict[str, str]:
    """Write every new package to GridFS; legacy inline rows remain readable."""
    if not content or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("Skill archive exceeds the size limit")
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Skill archive digest mismatch")
    file_id = uuid.uuid4().hex
    await _bucket(db).upload_from_stream_with_id(
        file_id, f"{digest}.zip", io.BytesIO(content),
        metadata={"main_id": main_id, "digest": digest},
    )
    return {"archive_gridfs_id": file_id}


async def read_archive(db: Any, row: dict[str, Any]) -> bytes:
    """Read either stored format and verify its immutable digest when present."""
    file_id = str(row.get("archive_gridfs_id") or "")
    if file_id:
        stream = await _bucket(db).open_download_stream(file_id)
        metadata = stream.metadata or {}
        if metadata.get("main_id") != row.get("main_id"):
            raise ValueError("Skill archive tenant mismatch")
        chunks: list[bytes] = []
        total = 0
        while chunk := await stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("Skill archive exceeds the size limit")
            chunks.append(chunk)
        content = b"".join(chunks)
    else:
        content = base64.b64decode(str(row.get("archive_base64") or ""), validate=True)
    digest = str(row.get("digest") or "")
    if digest and hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Skill archive digest mismatch")
    return content


async def delete_archive(db: Any, row: dict[str, Any]) -> None:
    file_id = str(row.get("archive_gridfs_id") or "")
    if file_id:
        await _bucket(db).delete(file_id)
