"""Authorize and stage a selected Skill package for one script job."""

from __future__ import annotations

import io
import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fcntl

from app.services.skill_packages.validator import (
    MAX_FILES, MAX_FILE_BYTES, MAX_UNCOMPRESSED_BYTES, SkillPackageError, _safe_zip_path,
)


@dataclass(frozen=True)
class SkillBundle:
    name: str
    root_prefix: str
    archive: bytes | None
    digest: str = ""


SHA256 = re.compile(r"^[0-9a-f]{64}$")


async def selected_skill_bundle(*, skill_id: str, tenant_id: str, user_id: str) -> SkillBundle | None:
    if not skill_id:
        return None
    from app.core.db import get_db
    from app.dsh_runtime.profile.skills.catalog import MongoSkillCatalog
    from app.dsh_runtime.profile.skills.resolver import require_selected_skill
    from app.services.skill_packages.archive_store import read_archive

    kind, skill = await require_selected_skill(
        MongoSkillCatalog(), skill_id=skill_id, tenant_id=tenant_id, user_id=user_id,
    )
    if kind != "skill" or not skill.get("package_id"):
        return None
    package = await get_db().skill_packages.find_one({
        "_id": str(skill["package_id"]), "main_id": tenant_id,
    })
    if package is None:
        raise ValueError("Selected Skill package is missing")
    prefix = str(package.get("root_prefix") or "")
    digest = str(package.get("digest") or "")
    if prefix and (_safe_zip_path(prefix) + "/") != prefix:
        raise ValueError("Selected Skill package has an invalid root prefix")
    if not SHA256.fullmatch(digest):
        raise ValueError("Selected Skill package has an invalid digest")
    cache_root = Path(os.environ.get("MOGO_SANDBOX_WORKSPACE_ROOT", "/workspaces")) / "skill-cache"
    cached_root = cache_root / digest / prefix
    archive = None if os.environ.get("MOGO_SANDBOX_MANAGER_URL") and (cached_root / "SKILL.md").is_file() else (
        await read_archive(get_db(), package)
    )
    return SkillBundle(
        name=str(package.get("slug") or ""),
        root_prefix=prefix, archive=archive, digest=digest,
    )


def stage_skill_bundle(bundle: SkillBundle, workspace: Path) -> Path:
    """Extract only inside this job's directory, with the install-time limits checked again."""
    if bundle.archive is None:
        raise ValueError("Selected Skill archive is not loaded")
    destination = workspace / "skill"
    destination.mkdir(mode=0o777)
    prefix = bundle.root_prefix
    if prefix and (_safe_zip_path(prefix) + "/") != prefix:
        raise SkillPackageError("unsafe_archive_path", "Invalid Skill root prefix")
    count = 0
    total = 0
    with zipfile.ZipFile(io.BytesIO(bundle.archive)) as archive:
        for info in archive.infolist():
            path = _safe_zip_path(info.filename)
            if info.is_dir() or path.startswith("__MACOSX/"):
                continue
            count += 1
            total += info.file_size
            if count > MAX_FILES or total > MAX_UNCOMPRESSED_BYTES or info.file_size > MAX_FILE_BYTES:
                raise SkillPackageError("package_limit", "Skill package exceeds the execution limits")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or info.flag_bits & 1:
                raise SkillPackageError("unsafe_archive_path", "Skill package contains an unsafe entry")
            if prefix and not path.startswith(prefix):
                raise SkillPackageError("unsafe_archive_path", "Skill package entry escapes its root")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise SkillPackageError("duplicate_archive_path", "Skill package contains duplicate paths")
            with archive.open(info) as source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            os.chmod(target, 0o555 if mode & 0o111 else 0o444)
    root = destination / prefix if prefix else destination
    if not (root / "SKILL.md").is_file():
        raise SkillPackageError("missing_skill_md", "Selected Skill package has no SKILL.md")
    return root


def cache_skill_bundle(bundle: SkillBundle, workspace_root: Path) -> str:
    """Keep one immutable copy for read-only mounts into short-lived jobs."""
    digest = bundle.digest or (hashlib.sha256(bundle.archive).hexdigest() if bundle.archive else "")
    if not SHA256.fullmatch(digest):
        raise ValueError("Selected Skill package has an invalid digest")
    if bundle.archive is not None and hashlib.sha256(bundle.archive).hexdigest() != digest:
        raise ValueError("Selected Skill package digest mismatch")
    cache_root = workspace_root / "skill-cache"
    cache_root.mkdir(mode=0o755, parents=True, exist_ok=True)
    destination = cache_root / digest
    lock_path = cache_root / f".{digest}.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if destination.is_dir():
            return digest
        if bundle.archive is None:
            raise ValueError("Selected Skill package cache is missing")
        temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=cache_root))
        try:
            stage_skill_bundle(bundle, temporary)
            (temporary / "skill").rename(destination)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    return digest
