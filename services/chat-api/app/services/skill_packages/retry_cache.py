"""Reuse the immutable Skill cache before reading a large archive again."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from app.execution_isolation.skill_bundle import SHA256, SkillBundle, cache_skill_bundle

from .archive_store import read_archive
from .validator import _safe_zip_path


async def ensure_retry_bundle_cached(db: Any, package: dict[str, Any]) -> str:
    digest = str(package["digest"])
    prefix = str(package.get("root_prefix") or "")
    if not SHA256.fullmatch(digest) or (prefix and (_safe_zip_path(prefix) + "/") != prefix):
        raise ValueError("Invalid Skill package cache path")
    root = Path(os.environ.get("MOGO_SANDBOX_WORKSPACE_ROOT", "/workspaces"))
    cached_skill = root / "skill-cache" / digest / prefix / "SKILL.md"
    archive = None if cached_skill.is_file() else await read_archive(db, package)
    bundle = SkillBundle(
        name=str(package["slug"]), root_prefix=prefix,
        archive=archive, digest=digest,
    )
    return await asyncio.to_thread(cache_skill_bundle, bundle, root)
