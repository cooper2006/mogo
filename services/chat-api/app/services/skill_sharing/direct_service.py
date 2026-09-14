from __future__ import annotations

import base64
import datetime
import secrets
import uuid
from typing import Any

from app.core.db import get_db
from app.core.tenant import add_main_scope, resolve_main_id

from .exporter import SkillShareExporter
from .distribution import SkillDistributionService
from .member_directory import SkillShareMemberDirectory
from .service import SHARE_COLLECTION, SkillShareError, SkillShareService, _utcnow
from .legacy_migration import LegacySkillShareMigration


DELIVERY_COLLECTION = "skill_share_deliveries"


class DirectSkillShareService:
    """Shares one immutable snapshot with many tenant members via lightweight delivery rows."""

    def __init__(
        self,
        *,
        exporter: SkillShareExporter | None = None,
        installer: SkillShareService | None = None,
        directory: SkillShareMemberDirectory | None = None,
        distribution: SkillDistributionService | None = None,
    ) -> None:
        self._exporter = exporter or SkillShareExporter()
        self._installer = installer or SkillShareService()
        self._directory = directory or SkillShareMemberDirectory()
        self._distribution = distribution or SkillDistributionService()
        self._legacy_migration = LegacySkillShareMigration(self._distribution)

    async def create(
        self, *, main_id: str, owner_user_id: str, skill_id: str, recipient_user_ids: list[str],
    ) -> dict[str, Any]:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        members = await self._directory.require_members(
            main_id=tenant_id, requester_user_id=owner_user_id, user_ids=recipient_user_ids,
        )
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
        owner = await self._directory_user(db, tenant_id, owner_user_id)
        now = _utcnow()
        share_id = uuid.uuid4().hex
        share = {
            "_id": share_id,
            "main_id": tenant_id,
            "owner_user_id": str(owner_user_id),
            "owner": owner,
            "source_skill_id": skill_id,
            "distribution_id": distribution["_id"],
            "release_id": release["_id"],
            "release_version": release["version"],
            "mode": "direct",
            "token_hash": secrets.token_hex(32),
            "status": "active",
            "archive_base64": base64.b64encode(snapshot.package.archive_bytes).decode("ascii"),
            "digest": snapshot.package.archive_digest,
            "package": snapshot.package.package_summary(),
            "profile": snapshot.profile,
            "created_at": now,
            "expires_at": None,
            "revoked_at": None,
            "recipient_count": len(members),
        }
        await db[SHARE_COLLECTION].insert_one(share)
        deliveries = []
        for member in members:
            recipient_id = str(member.get("_id") or "")
            deliveries.append({
                "_id": self._delivery_id(now),
                "main_id": tenant_id,
                "share_id": share_id,
                "source_skill_id": skill_id,
                "sender_user_id": str(owner_user_id),
                "recipient_user_id": recipient_id,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            })
        try:
            await db[DELIVERY_COLLECTION].insert_many(deliveries)
        except Exception:
            await db[SHARE_COLLECTION].delete_one({"_id": share_id, "main_id": tenant_id})
            raise
        await db[DELIVERY_COLLECTION].update_many(
            {
                "main_id": tenant_id,
                "sender_user_id": str(owner_user_id),
                "source_skill_id": skill_id,
                "recipient_user_id": {"$in": [row["recipient_user_id"] for row in deliveries]},
                "status": "pending",
                "share_id": {"$ne": share_id},
            },
            {"$set": {"status": "superseded", "updated_at": now}},
        )
        return {
            "shareId": share_id,
            "recipientCount": len(deliveries),
            "recipients": [self._directory.member_view(member) for member in members],
        }

    async def inbox(
        self, *, main_id: str, recipient_user_id: str, cursor: str = "", limit: int = 20,
    ) -> dict[str, Any]:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        page_size = min(max(int(limit), 1), 50)
        query: dict[str, Any] = {
            "main_id": tenant_id,
            "recipient_user_id": str(recipient_user_id),
            "status": "pending",
        }
        if cursor:
            query["_id"] = {"$lt": str(cursor)}
        deliveries = await db[DELIVERY_COLLECTION].find(query).sort("_id", -1).limit(page_size + 1).to_list(length=page_size + 1)
        has_more = len(deliveries) > page_size
        page = deliveries[:page_size]
        share_ids = [str(row.get("share_id") or "") for row in page]
        shares = await db[SHARE_COLLECTION].find({
            "main_id": tenant_id, "_id": {"$in": share_ids}, "status": "active",
        }).to_list(length=len(share_ids)) if share_ids else []
        by_id = {str(row.get("_id") or ""): row for row in shares}
        items = []
        for delivery in page:
            share = by_id.get(str(delivery.get("share_id") or ""))
            if not share:
                continue
            share = await self._legacy_migration.ensure_share(share)
            preview = await self._installer.preview_snapshot(row=share, recipient_user_id=recipient_user_id)
            items.append({
                "deliveryId": str(delivery.get("_id") or ""),
                "sender": dict(share.get("owner") or {}),
                "sharedAt": self._iso(delivery.get("created_at")),
                **preview,
            })
        pending_count = await db[DELIVERY_COLLECTION].count_documents({
            "main_id": tenant_id, "recipient_user_id": str(recipient_user_id), "status": "pending",
        })
        return {
            "items": items,
            "nextCursor": str(page[-1].get("_id") or "") if has_more and page else "",
            "hasMore": has_more,
            "pendingCount": pending_count,
        }

    async def pending_count(self, *, main_id: str, recipient_user_id: str) -> int:
        return await get_db()[DELIVERY_COLLECTION].count_documents({
            "main_id": resolve_main_id(main_id),
            "recipient_user_id": str(recipient_user_id),
            "status": "pending",
        })

    async def accept(
        self, *, main_id: str, recipient_user_id: str, delivery_id: str, replace_existing: bool = False,
    ) -> dict[str, Any]:
        db = get_db()
        scope = {
            "_id": delivery_id,
            "main_id": resolve_main_id(main_id),
            "recipient_user_id": str(recipient_user_id),
        }
        delivery = await db[DELIVERY_COLLECTION].find_one(scope)
        if delivery is None or delivery.get("status") in {"declined", "revoked", "superseded"}:
            raise SkillShareError("skill_share_delivery_unavailable", "This shared Skill is unavailable", status_code=404)
        if delivery.get("status") == "accepted":
            return dict(delivery.get("install_result") or {})
        if delivery.get("status") == "installing":
            raise SkillShareError("skill_share_installing", "This shared Skill is already being installed", status_code=409)
        claimed = await db[DELIVERY_COLLECTION].update_one(
            {**scope, "status": "pending"}, {"$set": {"status": "installing", "updated_at": _utcnow()}},
        )
        if not claimed.matched_count:
            raise SkillShareError("skill_share_delivery_unavailable", "This shared Skill is unavailable", status_code=409)
        share = await db[SHARE_COLLECTION].find_one({
            "_id": str(delivery.get("share_id") or ""), "main_id": resolve_main_id(main_id), "status": "active",
        })
        if share is None:
            await self._restore_pending(db, scope)
            raise SkillShareError("skill_share_delivery_unavailable", "This shared Skill is unavailable", status_code=404)
        try:
            installed = await self._installer.install_snapshot(
                row=share, recipient_user_id=recipient_user_id, replace_existing=replace_existing,
            )
        except Exception:
            await self._restore_pending(db, scope)
            raise
        now = _utcnow()
        await db[DELIVERY_COLLECTION].update_one(
            {**scope, "status": "installing"},
            {"$set": {"status": "accepted", "accepted_at": now, "updated_at": now, "install_result": installed}},
        )
        return installed

    async def decline(self, *, main_id: str, recipient_user_id: str, delivery_id: str) -> None:
        result = await get_db()[DELIVERY_COLLECTION].update_one(
            {
                "_id": delivery_id,
                "main_id": resolve_main_id(main_id),
                "recipient_user_id": str(recipient_user_id),
                "status": "pending",
            },
            {"$set": {"status": "declined", "updated_at": _utcnow()}},
        )
        if not result.matched_count:
            raise SkillShareError("skill_share_delivery_unavailable", "This shared Skill is unavailable", status_code=404)

    @staticmethod
    async def _directory_user(db: Any, main_id: str, user_id: str) -> dict[str, str]:
        from .member_directory import member_id_candidates
        row = await db.end_users.find_one(add_main_scope({
            "_id": {"$in": member_id_candidates([user_id])}, "status": "active",
        }, main_id), {"name": 1, "login_name": 1, "email": 1})
        if row is None:
            return {"userId": str(user_id), "displayName": "", "username": "", "email": ""}
        return SkillShareMemberDirectory.member_view(row)

    @staticmethod
    async def _restore_pending(db: Any, scope: dict[str, Any]) -> None:
        await db[DELIVERY_COLLECTION].update_one(
            {**scope, "status": "installing"}, {"$set": {"status": "pending", "updated_at": _utcnow()}},
        )

    @staticmethod
    def _iso(value: Any) -> str:
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        return ""

    @staticmethod
    def _delivery_id(created_at: datetime.datetime) -> str:
        # Timestamp prefix gives string IDs a stable newest-first cursor order.
        micros = int(created_at.timestamp() * 1_000_000)
        return f"{micros:016x}{uuid.uuid4().hex}"
