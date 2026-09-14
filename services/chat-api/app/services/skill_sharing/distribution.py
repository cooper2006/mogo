from __future__ import annotations

import base64
import datetime
import json
import uuid
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id

from .exporter import ShareSnapshot, SkillShareExporter


DISTRIBUTION_COLLECTION = "skill_distributions"
MEMBER_COLLECTION = "skill_distribution_members"
DISTRIBUTION_RELEASE_COLLECTION = "skill_distribution_releases"
NOTIFICATION_COLLECTION = "skill_update_notifications"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class SkillDistributionService:
    """Stable audience and releases above immutable Skill share snapshots."""

    async def ensure(
        self, *, main_id: str, owner_user_id: str, source_skill_id: str,
    ) -> dict[str, Any]:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        query = {
            "main_id": tenant_id,
            "owner_user_id": str(owner_user_id),
            "source_skill_id": str(source_skill_id),
            "status": "active",
        }
        current = await db[DISTRIBUTION_COLLECTION].find_one(query)
        if current:
            return current
        row = {"_id": uuid.uuid4().hex, **query, "created_at": _utcnow(), "updated_at": _utcnow()}
        await db[DISTRIBUTION_COLLECTION].insert_one(row)
        await db.user_skills.update_one(
            {"_id": str(source_skill_id), "main_id": tenant_id, "user_id": str(owner_user_id)},
            {"$set": {"distribution_id": row["_id"]}},
        )
        return row

    async def ensure_release(
        self,
        *,
        distribution: dict[str, Any],
        snapshot: ShareSnapshot,
        release_id: str = "",
        version: str = "",
        release_notes: str = "",
    ) -> dict[str, Any]:
        db = get_db()
        query = {
            "main_id": str(distribution["main_id"]),
            "distribution_id": str(distribution["_id"]),
            "digest": snapshot.package.archive_digest,
        }
        current = await db[DISTRIBUTION_RELEASE_COLLECTION].find_one(query)
        if current:
            return current
        row = {
            "_id": str(release_id or uuid.uuid4().hex),
            **query,
            "owner_user_id": str(distribution["owner_user_id"]),
            "source_skill_id": str(distribution["source_skill_id"]),
            "version": str(version or snapshot.package.version or "1.0.0"),
            "release_notes": str(release_notes or "").strip()[:2000],
            "archive_base64": base64.b64encode(snapshot.package.archive_bytes).decode("ascii"),
            "package": snapshot.package.package_summary(),
            "profile": snapshot.profile,
            "status": "active",
            "created_at": _utcnow(),
        }
        await db[DISTRIBUTION_RELEASE_COLLECTION].insert_one(row)
        await db[DISTRIBUTION_COLLECTION].update_one(
            {"_id": distribution["_id"], "main_id": distribution["main_id"]},
            {"$set": {"latest_release_id": row["_id"], "latest_version": row["version"], "updated_at": _utcnow()}},
        )
        return row

    async def publish_from_skill(
        self,
        *,
        main_id: str,
        owner_user_id: str,
        source_skill_id: str,
        release_id: str = "",
        version: str = "",
        release_notes: str = "",
    ) -> dict[str, Any] | None:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        distribution = await db[DISTRIBUTION_COLLECTION].find_one({
            "main_id": tenant_id,
            "owner_user_id": str(owner_user_id),
            "source_skill_id": str(source_skill_id),
            "status": "active",
        })
        if distribution is None:
            return None
        skill = await db.user_skills.find_one({
            "_id": str(source_skill_id), "main_id": tenant_id, "user_id": str(owner_user_id),
        })
        if skill is None:
            return None
        snapshot = await SkillShareExporter().export(db, skill)
        release = await self.ensure_release(
            distribution=distribution,
            snapshot=snapshot,
            release_id=release_id,
            version=version,
            release_notes=release_notes,
        )
        await self._notify_members(distribution=distribution, release=release)
        return release

    async def record_accept(
        self,
        *,
        release: dict[str, Any],
        recipient_user_id: str,
        installed_skill_id: str,
    ) -> None:
        db = get_db()
        query = {
            "main_id": str(release.get("main_id") or "default"),
            "distribution_id": str(release.get("distribution_id") or ""),
            "recipient_user_id": str(recipient_user_id),
        }
        if not query["distribution_id"]:
            return
        current = await db[MEMBER_COLLECTION].find_one(query)
        values = {
            "owner_user_id": str(release.get("owner_user_id") or ""),
            "source_skill_id": str(release.get("source_skill_id") or ""),
            "installed_skill_id": str(installed_skill_id),
            "installed_release_id": str(release.get("_id") or ""),
            "installed_version": str(release.get("version") or ""),
            "installed_digest": str(release.get("digest") or ""),
            "status": "active",
            "updated_at": _utcnow(),
        }
        if current:
            await db[MEMBER_COLLECTION].update_one({"_id": current["_id"]}, {"$set": values})
        else:
            await db[MEMBER_COLLECTION].insert_one({"_id": uuid.uuid4().hex, **query, **values, "created_at": _utcnow()})

    async def list_updates(self, *, main_id: str, recipient_user_id: str, limit: int = 50) -> dict[str, Any]:
        db = get_db()
        query = {
            "main_id": resolve_main_id(main_id),
            "recipient_user_id": str(recipient_user_id),
            "status": "pending",
        }
        count = await db[NOTIFICATION_COLLECTION].count_documents(query)
        rows = await db[NOTIFICATION_COLLECTION].find(query).sort("created_at", -1).limit(min(max(limit, 1), 50)).to_list(length=min(max(limit, 1), 50))
        installed_ids = list({str(row.get("installed_skill_id") or "") for row in rows} - {""})
        release_ids = list({str(row.get("release_id") or "") for row in rows} - {""})
        installed_rows = await db.user_skills.find({
            "_id": {"$in": installed_ids}, "main_id": query["main_id"],
            "user_id": str(recipient_user_id),
        }).to_list(length=len(installed_ids)) if installed_ids else []
        releases = await db[DISTRIBUTION_RELEASE_COLLECTION].find({
            "_id": {"$in": release_ids}, "main_id": query["main_id"], "status": "active",
        }).to_list(length=len(release_ids)) if release_ids else []
        installed_by_id = {str(row.get("_id") or ""): row for row in installed_rows}
        releases_by_id = {str(row.get("_id") or ""): row for row in releases}
        items = []
        for row in rows:
            installed = installed_by_id.get(str(row.get("installed_skill_id") or ""))
            release = releases_by_id.get(str(row.get("release_id") or ""))
            item = self.notification_view(row, installed=installed, release=release)
            item["localModified"] = bool(installed) and (bool(installed.get("locally_modified")) or str(installed.get("package_digest") or "") != str(row.get("installed_digest") or ""))
            items.append(item)
        return {"items": items, "pendingCount": count}

    async def install_update(
        self, *, main_id: str, recipient_user_id: str, notification_id: str, confirm_replace: bool = False,
    ) -> dict[str, Any]:
        from .service import SkillShareError, SkillShareService

        db = get_db()
        tenant_id = resolve_main_id(main_id)
        query = {
            "_id": notification_id,
            "main_id": tenant_id,
            "recipient_user_id": str(recipient_user_id),
            "status": "pending",
        }
        notification = await db[NOTIFICATION_COLLECTION].find_one(query)
        if notification is None:
            raise SkillShareError("skill_update_unavailable", "This Skill update is unavailable", status_code=404)
        release = await db[DISTRIBUTION_RELEASE_COLLECTION].find_one({
            "_id": str(notification.get("release_id") or ""),
            "main_id": tenant_id,
            "status": "active",
        })
        if release is None:
            raise SkillShareError("skill_update_unavailable", "This Skill update is unavailable", status_code=404)
        current = await db.user_skills.find_one({
            "_id": str(notification.get("installed_skill_id") or ""), "main_id": tenant_id,
            "user_id": str(recipient_user_id),
        })
        local_modified = bool(current) and (bool(current.get("locally_modified")) or str(current.get("package_digest") or "") != str(notification.get("installed_digest") or ""))
        if local_modified and not confirm_replace:
            raise SkillShareError("skill_update_local_changes", "The installed Skill has local changes", status_code=409)
        previous_source = dict((current or {}).get("package_source") or {})
        installed = await SkillShareService().install_snapshot(
            row={**release, "mode": "update", "_id": release["_id"], "release_id": release["_id"], "owner": previous_source.get("sender") or {}},
            recipient_user_id=str(recipient_user_id),
            replace_existing=True,
        )
        await self.record_accept(
            release=release,
            recipient_user_id=recipient_user_id,
            installed_skill_id=str(installed.get("id") or ""),
        )
        await db[NOTIFICATION_COLLECTION].update_one(query, {"$set": {"status": "installed", "updated_at": _utcnow()}})
        return installed

    async def _notify_members(self, *, distribution: dict[str, Any], release: dict[str, Any]) -> None:
        db = get_db()
        members = await db[MEMBER_COLLECTION].find({
            "main_id": distribution["main_id"],
            "distribution_id": distribution["_id"],
            "status": "active",
            "installed_digest": {"$ne": release["digest"]},
        }).to_list(length=100_000)
        for member in members:
            query = {
                "main_id": distribution["main_id"],
                "distribution_id": distribution["_id"],
                "recipient_user_id": member["recipient_user_id"],
                "release_id": release["_id"],
            }
            if await db[NOTIFICATION_COLLECTION].find_one(query):
                continue
            await db[NOTIFICATION_COLLECTION].insert_one({
                "_id": uuid.uuid4().hex,
                **query,
                "installed_skill_id": str(member.get("installed_skill_id") or ""),
                "installed_digest": str(member.get("installed_digest") or ""),
                "name": str((release.get("profile") or {}).get("name") or (release.get("package") or {}).get("slug") or "Skill"),
                "current_version": str(member.get("installed_version") or ""),
                "new_version": str(release.get("version") or ""),
                "release_notes": str(release.get("release_notes") or ""),
                "status": "pending",
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            })

    @classmethod
    def notification_view(
        cls, row: dict[str, Any], *, installed: dict[str, Any] | None = None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created = row.get("created_at")
        installed = installed or {}
        release = release or {}
        return {
            "id": str(row.get("_id") or ""),
            "distributionId": str(row.get("distribution_id") or ""),
            "skillId": str(row.get("installed_skill_id") or ""),
            "name": str(row.get("name") or "Skill"),
            "currentVersion": str(row.get("current_version") or installed.get("package_version") or installed.get("published_version") or ""),
            "newVersion": str(row.get("new_version") or release.get("version") or ""),
            "releaseNotes": str(row.get("release_notes") or ""),
            "changes": cls._changed_sections(installed, dict(release.get("profile") or {})),
            "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else "",
        }

    @staticmethod
    def _changed_sections(installed: dict[str, Any], target: dict[str, Any]) -> list[str]:
        if not target:
            return ["package_content"]

        def different(left: Any, right: Any) -> bool:
            return json.dumps(left, ensure_ascii=False, sort_keys=True, default=str) != json.dumps(right, ensure_ascii=False, sort_keys=True, default=str)

        changes: list[str] = []
        for key in ("name", "description", "scenario"):
            if different(installed.get(key), target.get(key)):
                changes.append(key)
        if different(installed.get("skill_markdown"), target.get("skill_markdown")):
            changes.append("instructions")
        if any(different(installed.get(key), target.get(key)) for key in ("config", "input_profile", "contract_json", "advanced")):
            changes.append("configuration")
        return changes or ["package_content"]
