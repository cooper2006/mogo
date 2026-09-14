from __future__ import annotations

import base64
import logging
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.services.skill_packages import validate_skill_package

from .distribution import SkillDistributionService
from .exporter import ShareSnapshot


logger = logging.getLogger(__name__)


class LegacySkillShareMigration:
    """Lazily attaches pre-distribution shares and installs to a stable identity."""

    def __init__(self, distribution: SkillDistributionService | None = None) -> None:
        self._distribution = distribution or SkillDistributionService()

    async def migrate_owned(self, *, main_id: str, owner_user_id: str) -> None:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        shares = await db.skill_shares.find({
            "main_id": tenant_id, "owner_user_id": str(owner_user_id), "status": "active",
        }).to_list(length=10_000)
        for share in shares:
            if share.get("distribution_id") and share.get("release_id"):
                continue
            try:
                await self.ensure_share(share)
            except Exception as exc:
                logger.warning("legacy owned Skill share migration failed", extra={"share_id": str(share.get("_id") or ""), "error": str(exc)[:500]})

    async def migrate_installed(self, *, main_id: str, recipient_user_id: str) -> None:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        skills = await db.user_skills.find({
            "main_id": tenant_id, "user_id": str(recipient_user_id),
        }).to_list(length=10_000)
        for skill in skills:
            source = dict(skill.get("package_source") or {})
            if source.get("kind") != "movo_share" or source.get("distributionId"):
                continue
            share_id = str(source.get("shareId") or "")
            share = await db.skill_shares.find_one({"_id": share_id, "main_id": tenant_id})
            if share is None:
                continue
            try:
                upgraded = await self.ensure_share(share)
            except Exception as exc:
                logger.warning("legacy installed Skill share migration failed", extra={"share_id": share_id, "error": str(exc)[:500]})
                continue
            distribution_id = str(upgraded.get("distribution_id") or "")
            release_id = str(upgraded.get("release_id") or "")
            if not distribution_id or not release_id:
                continue
            source.update({"distributionId": distribution_id, "releaseId": release_id})
            await db.user_skills.update_one(
                {"_id": skill["_id"], "main_id": tenant_id, "user_id": str(recipient_user_id)},
                {"$set": {"package_source": source, "distribution_id": distribution_id}},
            )
            await self._distribution.record_accept(
                release={
                    **upgraded,
                    "_id": release_id,
                    "distribution_id": distribution_id,
                    "version": str(upgraded.get("release_version") or (upgraded.get("package") or {}).get("version") or "1.0.0"),
                },
                recipient_user_id=str(recipient_user_id),
                installed_skill_id=str(skill["_id"]),
            )

    async def ensure_share(self, share: dict[str, Any]) -> dict[str, Any]:
        if share.get("distribution_id") and share.get("release_id"):
            return share
        owner_id, source_skill_id = str(share.get("owner_user_id") or ""), str(share.get("source_skill_id") or "")
        if not owner_id or not source_skill_id:
            return share
        try:
            archive = base64.b64decode(str(share.get("archive_base64") or ""), validate=True)
            package = validate_skill_package(archive)
        except Exception:
            return share
        distribution = await self._distribution.ensure(
            main_id=str(share.get("main_id") or "default"),
            owner_user_id=owner_id,
            source_skill_id=source_skill_id,
        )
        release = await self._distribution.ensure_release(
            distribution=distribution,
            snapshot=ShareSnapshot(package=package, profile=dict(share.get("profile") or {})),
            version=str(share.get("release_version") or package.version or "1.0.0"),
        )
        updates = {
            "distribution_id": str(distribution["_id"]),
            "release_id": str(release["_id"]),
            "release_version": str(release.get("version") or package.version or "1.0.0"),
        }
        await get_db().skill_shares.update_one(
            {"_id": share["_id"], "main_id": share["main_id"]}, {"$set": updates},
        )
        return {**share, **updates}


legacy_skill_share_migration = LegacySkillShareMigration()
