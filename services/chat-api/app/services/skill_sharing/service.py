from __future__ import annotations

import base64
import datetime
import hashlib
import secrets
import uuid
from typing import Any

from app.core.db import get_db
from app.core.tenant import add_main_scope, resolve_main_id
from app.services.skill_packages import SkillPackageInstaller, validate_skill_package

from .exporter import SkillShareExporter
from .distribution import SkillDistributionService


SHARE_COLLECTION = "skill_shares"


class SkillShareError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class SkillShareService:
    def __init__(
        self,
        *,
        exporter: SkillShareExporter | None = None,
        installer: SkillPackageInstaller | None = None,
    ) -> None:
        self._exporter = exporter or SkillShareExporter()
        self._installer = installer or SkillPackageInstaller()
        self._distribution = SkillDistributionService()

    async def create(
        self, *, main_id: str, owner_user_id: str, skill_id: str, expires_in_days: int | None = 30,
    ) -> dict[str, Any]:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        skill = await db.user_skills.find_one(add_main_scope({
            "_id": skill_id, "user_id": str(owner_user_id),
        }, tenant_id))
        if skill is None:
            raise SkillShareError("skill_not_found", "Skill not found", status_code=404)
        if skill.get("authoring_mode") == "platform" and not skill.get("published_version"):
            raise SkillShareError("skill_publish_required", "Publish this Skill before sharing it", status_code=409)
        snapshot = await self._exporter.export(db, skill)
        distribution = await self._distribution.ensure(
            main_id=tenant_id, owner_user_id=owner_user_id, source_skill_id=skill_id,
        )
        release = await self._distribution.ensure_release(
            distribution=distribution,
            snapshot=snapshot,
            release_id=str(skill.get("published_release_id") or ""),
            version=str(skill.get("published_version") or skill.get("package_version") or ""),
        )
        token = secrets.token_urlsafe(32)
        now = _utcnow()
        expires_at = now + datetime.timedelta(days=expires_in_days) if expires_in_days is not None else None
        share_id = uuid.uuid4().hex
        row = {
            "_id": share_id,
            "main_id": tenant_id,
            "owner_user_id": str(owner_user_id),
            "source_skill_id": skill_id,
            "distribution_id": distribution["_id"],
            "release_id": release["_id"],
            "release_version": release["version"],
            "owner": {"userId": str(owner_user_id)},
            "token_hash": self._token_hash(token),
            "status": "active",
            "archive_base64": base64.b64encode(snapshot.package.archive_bytes).decode("ascii"),
            "digest": snapshot.package.archive_digest,
            "package": snapshot.package.package_summary(),
            "profile": snapshot.profile,
            "created_at": now,
            "expires_at": expires_at,
            "revoked_at": None,
        }
        await db[SHARE_COLLECTION].insert_one(row)
        return {"shareId": share_id, "token": token, **self._preview(row)}

    async def preview(self, *, main_id: str, recipient_user_id: str, token: str) -> dict[str, Any]:
        row = await self._active_share(main_id=main_id, token=token)
        return await self.preview_snapshot(row=row, recipient_user_id=recipient_user_id)

    async def install(
        self, *, main_id: str, recipient_user_id: str, token: str, replace_existing: bool = False,
    ) -> dict[str, Any]:
        db = get_db()
        row = await self._active_share(main_id=main_id, token=token)
        return await self.install_snapshot(
            row=row, recipient_user_id=recipient_user_id, replace_existing=replace_existing,
        )

    async def preview_snapshot(self, *, row: dict[str, Any], recipient_user_id: str) -> dict[str, Any]:
        conflict = await self._conflict(row=row, recipient_user_id=recipient_user_id)
        return {**self._preview(row), **conflict}

    async def install_snapshot(
        self, *, row: dict[str, Any], recipient_user_id: str, replace_existing: bool = False,
    ) -> dict[str, Any]:
        db = get_db()
        conflict = await self._conflict(row=row, recipient_user_id=recipient_user_id)
        if conflict["alreadyInstalled"]:
            existing = await db.user_skills.find_one({
                "_id": conflict["existingSkillId"], "main_id": row["main_id"], "user_id": recipient_user_id,
            })
            installed_result = self._installed_result(existing or {}, row, duplicate=True)
            await self._record_distribution_accept(row, recipient_user_id, installed_result)
            return installed_result
        if conflict["hasConflict"] and not replace_existing:
            raise SkillShareError("skill_share_conflict", "A different Skill with the same package name is already installed", status_code=409)
        try:
            archive = base64.b64decode(str(row.get("archive_base64") or ""), validate=True)
            package = validate_skill_package(archive)
        except Exception as exc:
            raise SkillShareError("skill_share_snapshot_invalid", "The shared Skill snapshot is unavailable") from exc
        result = await self._installer.install(
            package,
            scope="personal",
            main_id=row["main_id"],
            user_id=recipient_user_id,
            package_source=self._package_source(row),
        )
        profile = dict(row.get("profile") or {})
        if profile:
            profile.update({"visibility": "private", "locally_modified": False, "updated_at": _utcnow()})
            await db.user_skills.update_one(
                {"_id": result["id"], "main_id": row["main_id"], "user_id": recipient_user_id},
                {"$set": profile},
            )
        installed = await db.user_skills.find_one({
            "_id": result["id"], "main_id": row["main_id"], "user_id": recipient_user_id,
        })
        installed_result = self._installed_result(installed or {}, row, duplicate=bool(result.get("duplicate")))
        await self._record_distribution_accept(row, recipient_user_id, installed_result)
        return installed_result

    async def _record_distribution_accept(
        self, row: dict[str, Any], recipient_user_id: str, installed_result: dict[str, Any],
    ) -> None:
        if not row.get("distribution_id"):
            return
        await self._distribution.record_accept(
            release={
                **row,
                "_id": str(row.get("release_id") or row.get("_id") or ""),
                "distribution_id": str(row.get("distribution_id") or ""),
                "version": str(row.get("release_version") or row.get("version") or (row.get("package") or {}).get("version") or ""),
            },
            recipient_user_id=recipient_user_id,
            installed_skill_id=str(installed_result.get("id") or ""),
        )

    async def revoke(self, *, main_id: str, owner_user_id: str, skill_id: str, share_id: str) -> None:
        db = get_db()
        result = await db[SHARE_COLLECTION].update_one(
            {
                "_id": share_id,
                "main_id": resolve_main_id(main_id),
                "owner_user_id": str(owner_user_id),
                "source_skill_id": skill_id,
                "status": "active",
            },
            {"$set": {"status": "revoked", "revoked_at": _utcnow()}},
        )
        if not result.matched_count:
            raise SkillShareError("skill_share_not_found", "Active Skill share not found", status_code=404)

    async def _active_share(self, *, main_id: str, token: str) -> dict[str, Any]:
        db = get_db()
        row = await db[SHARE_COLLECTION].find_one({
            "main_id": resolve_main_id(main_id), "token_hash": self._token_hash(token),
        })
        if row is None or row.get("status") != "active":
            raise SkillShareError("skill_share_unavailable", "This Skill share is unavailable", status_code=404)
        expires_at = row.get("expires_at")
        if isinstance(expires_at, datetime.datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
            if expires_at <= _utcnow():
                raise SkillShareError("skill_share_expired", "This Skill share has expired", status_code=410)
        return row

    async def _conflict(self, *, row: dict[str, Any], recipient_user_id: str) -> dict[str, Any]:
        db = get_db()
        package = dict(row.get("package") or {})
        existing = await db.user_skills.find_one({
            "main_id": row["main_id"],
            "user_id": str(recipient_user_id),
            "package_slug": str(package.get("slug") or ""),
        })
        if existing is None:
            return {"alreadyInstalled": False, "hasConflict": False, "existingSkillId": ""}
        same = str(existing.get("package_digest") or "") == str(row.get("digest") or "")
        return {
            "alreadyInstalled": same,
            "hasConflict": not same,
            "existingSkillId": str(existing.get("_id") or ""),
        }

    @staticmethod
    def _preview(row: dict[str, Any]) -> dict[str, Any]:
        package = dict(row.get("package") or {})
        profile = dict(row.get("profile") or {})
        expires_at = row.get("expires_at")
        return {
            "shareId": str(row.get("_id") or ""),
            "name": str(profile.get("name") or package.get("slug") or "Skill"),
            "description": str(profile.get("description") or ""),
            "type": str(profile.get("type") or package.get("kind") or "ordinary"),
            "version": str(package.get("version") or "1.0.0"),
            "fileCount": len(package.get("files") or []),
            "childCount": len(package.get("children") or []),
            "expiresAt": expires_at.isoformat() if isinstance(expires_at, datetime.datetime) else "",
        }

    @staticmethod
    def _installed_result(skill: dict[str, Any], row: dict[str, Any], *, duplicate: bool) -> dict[str, Any]:
        package = dict(row.get("package") or {})
        return {
            "id": str(skill.get("_id") or ""),
            "name": str(skill.get("name") or package.get("slug") or "Skill"),
            "type": str(skill.get("type") or package.get("kind") or "ordinary"),
            "version": str(package.get("version") or "1.0.0"),
            "duplicate": duplicate,
            "enabled": bool(skill.get("enabled", skill.get("is_active", True))),
        }

    @staticmethod
    def _package_source(row: dict[str, Any]) -> dict[str, Any]:
        source = {
            "kind": "movo_share",
            "mode": str(row.get("mode") or "link"),
            "shareId": str(row["_id"]),
            "sourceSkillId": str(row["source_skill_id"]),
        }
        if row.get("distribution_id"):
            source["distributionId"] = str(row["distribution_id"])
        if row.get("release_id"):
            source["releaseId"] = str(row["release_id"])
        owner = dict(row.get("owner") or {})
        sender = {
            key: str(owner.get(key) or "")
            for key in ("userId", "displayName", "username")
            if owner.get(key)
        }
        if sender:
            source["sender"] = sender
        return source

    @staticmethod
    def _token_hash(token: str) -> str:
        value = str(token or "").strip()
        if not value:
            raise SkillShareError("skill_share_token_required", "A Skill share token is required")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
