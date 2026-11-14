"""Start isolated dependency preparation after a package is persisted."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from .validator import ValidatedSkillPackage


LOG = logging.getLogger(__name__)
DEPENDENCY_FILES = frozenset({"requirements.txt", "package.json", "apt-packages.txt"})


def _start(package: ValidatedSkillPackage) -> str:
    from app.execution_isolation.skill_bundle import SkillBundle, cache_skill_bundle

    root = Path(os.environ.get("MOGO_SANDBOX_WORKSPACE_ROOT", "/workspaces"))
    cache_skill_bundle(SkillBundle(
        name=package.name, root_prefix=package.root_prefix,
        archive=package.archive_bytes, digest=package.archive_digest,
    ), root)
    url = os.environ["MOGO_SANDBOX_MANAGER_URL"].rstrip("/")
    token = os.environ.get("MOGO_SANDBOX_MANAGER_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Sandbox manager token is missing")
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.post(
            f"{url}/v1/skill-environments",
            json={"digest": package.archive_digest},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return str(response.json().get("status") or "preparing")


async def prewarm_skill_dependencies(package: ValidatedSkillPackage) -> str:
    if not os.environ.get("MOGO_SANDBOX_MANAGER_URL", "").strip():
        return "disabled"
    if not any(item.get("path") in DEPENDENCY_FILES for item in package.files):
        return "not_required"
    try:
        return await asyncio.to_thread(_start, package)
    except Exception:
        LOG.exception("Skill dependency prewarm could not be started: %s", package.name)
        return "unavailable"
