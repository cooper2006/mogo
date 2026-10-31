"""Resolve execution readiness for installed Skill packages."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from .dependency_status import dependency_status
from .prewarm import DEPENDENCY_FILES
from app.core.db import get_db
from .pending_upgrade import promote_if_ready
from .retry_cache import ensure_retry_bundle_cached


LOG = logging.getLogger(__name__)


def needs_environment(skill: dict[str, Any]) -> bool:
    if (skill.get("pending_package") or {}).get("digest"):
        return True
    if "package_requires_environment" in skill:
        return bool(skill["package_requires_environment"])
    return bool(skill.get("package_digest")) and any(
        str(item.get("path") or "") in DEPENDENCY_FILES
        for item in skill.get("package_files") or [] if isinstance(item, dict)
    )


async def environment_status(skill: dict[str, Any]) -> str | None:
    if not needs_environment(skill):
        return None
    pending = skill.get("pending_package") or {}
    status = await dependency_status(str(pending.get("digest") or skill["package_digest"]))
    if status == "ready" and pending:
        await promote_if_ready(skill)
    return status


async def attach_environment_status(skills: list[dict[str, Any]]) -> None:
    unresolved = {
        str(skill.get("package_id")) for skill in skills
        if skill.get("package_id") and skill.get("package_digest") and "package_requires_environment" not in skill
        and not skill.get("pending_package")
        and not skill.get("package_files")
    }
    if unresolved:
        packages = await get_db().skill_packages.find(
            {"_id": {"$in": list(unresolved)}},
            {"files": {"$elemMatch": {"path": {"$in": list(DEPENDENCY_FILES)}}}},
        ).to_list(length=len(unresolved))
        required = {str(item["_id"]): bool(item.get("files")) for item in packages}
        for skill in skills:
            package_id = str(skill.get("package_id") or "")
            if package_id in required:
                skill["package_requires_environment"] = required[package_id]
    semaphore = asyncio.Semaphore(8)

    async def attach(skill: dict[str, Any]) -> None:
        if not needs_environment(skill):
            return
        async with semaphore:
            skill["environment_status"] = await environment_status(skill)

    await asyncio.gather(*(attach(skill) for skill in skills))


async def retry_environment(skill: dict[str, Any]) -> str | None:
    if not needs_environment(skill):
        return None
    url = os.environ.get("MOGO_SANDBOX_MANAGER_URL", "").strip().rstrip("/")
    token = os.environ.get("MOGO_SANDBOX_MANAGER_TOKEN", "")
    if not url or len(token) < 32:
        LOG.warning("Skill dependency retry unavailable: sandbox manager configuration is missing")
        return "unavailable"
    try:
        package_id = str((skill.get("pending_package") or {}).get("fields", {}).get("package_id") or skill.get("package_id") or "")
        package = await get_db().skill_packages.find_one({"_id": package_id})
        if not package:
            LOG.warning("Skill dependency retry unavailable: package record is missing for skill %s", skill.get("_id") or skill.get("id"))
            return "unavailable"
        await ensure_retry_bundle_cached(get_db(), package)
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.post(
                f"{url}/v1/skill-environments",
                json={"digest": str((skill.get("pending_package") or {}).get("digest") or skill["package_digest"])},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return str(response.json().get("status") or "preparing")
    except (httpx.HTTPError, ValueError, OSError, KeyError):
        LOG.exception("Skill dependency retry could not be started")
        return "unavailable"
