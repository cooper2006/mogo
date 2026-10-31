"""Tenant-scoped reads of selected entries in a sandbox task archive."""

from __future__ import annotations

import asyncio
import hashlib
import re
import zipfile
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Iterator

from fastapi import HTTPException

from app.core.db import get_db
from .archive_access import open_audit_archive


MAX_TEXT_BYTES = 2 * 1024 * 1024
ALLOWED_KINDS = {"source", "stdout", "stderr"}


def extract_text(archive: zipfile.ZipFile, path: str) -> str:
    try:
        info = archive.getinfo(path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit_entry_not_found") from exc
    if info.file_size > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail="audit_entry_too_large")
    return archive.read(info).decode("utf-8", errors="replace")


async def _audit_call(tenant_id: str, message_id: str, call_id: str) -> tuple[str, dict]:
    row = await get_db().sandbox_task_audits.find_one(
        {"_id": f"{tenant_id}:{message_id}", "tenant_id": tenant_id, "message_id": message_id},
        {"_id": 0, "object_path": 1, "calls": 1},
    )
    if not row:
        raise HTTPException(status_code=404, detail="audit_not_found")
    call = next((item for item in row.get("calls") or []
                 if isinstance(item, dict) and item.get("call_id") == call_id), None)
    if call is None or not call_id.isalnum():
        raise HTTPException(status_code=404, detail="audit_call_not_found")
    return str(row["object_path"]), call


async def read_call_text(tenant_id: str, message_id: str, call_id: str, kind: str) -> str:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=404, detail="audit_entry_not_found")
    object_path, _ = await _audit_call(tenant_id, message_id, call_id)
    path = (f"work/calls/{call_id}/plugin.py" if kind == "source"
            else f"audit/{call_id}/{kind}.log")
    return await asyncio.to_thread(_read_text, object_path, call_id, kind, path)


def _read_text(object_path: str, call_id: str, kind: str, path: str) -> str:
    with open_audit_archive(object_path) as archive:
        if kind == "source" and path not in archive.namelist():
            path = f"work/calls/{call_id}/source.py"
        return extract_text(archive, path)


@contextmanager
def open_call_file(
    object_path: str, call_id: str, path: str, expected_digest: str,
) -> Iterator[tuple[Iterator[bytes], int]]:
    parts = PurePosixPath(path).parts
    if (not parts or path.startswith("/") or ".." in parts
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)):
        raise HTTPException(status_code=404, detail="audit_file_not_found")
    entry = f"audit/{call_id}/files/{path}"
    with open_audit_archive(object_path) as archive:
        try:
            info = archive.getinfo(entry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="audit_file_not_found") from exc
        def chunks() -> Iterator[bytes]:
            digest = hashlib.sha256()
            with archive.open(info) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    yield chunk
            if digest.hexdigest() != expected_digest:
                raise ValueError("Audit file checksum mismatch")
        yield chunks(), info.file_size


async def call_file_metadata(
    tenant_id: str, message_id: str, call_id: str, file_index: int,
) -> tuple[str, dict]:
    object_path, call = await _audit_call(tenant_id, message_id, call_id)
    files = call.get("files") or []
    if file_index < 0 or file_index >= len(files) or not isinstance(files[file_index], dict):
        raise HTTPException(status_code=404, detail="audit_file_not_found")
    return object_path, files[file_index]
