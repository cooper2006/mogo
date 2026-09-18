from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from app.core.db import get_db
from app.core.tenant import resolve_main_id

from .access import GRANT_COLLECTION, RESOURCE_COLLECTION


FEEDBACK_NOTIFICATION_COLLECTION = "resource_feedback_notifications"


@dataclass(frozen=True)
class InactiveKnowledgeAccess:
    resource: dict[str, Any]
    grant: dict[str, Any]

    @property
    def deleted(self) -> bool:
        return self.resource.get("deleted_at") is not None


class PersonalKnowledgeInactiveAccessService:
    """Resolve and acknowledge former access without restoring content access."""

    async def resolve(
        self, *, main_id: str, user_id: str, resource_id: str,
    ) -> InactiveKnowledgeAccess | None:
        db, tenant_id = get_db(), resolve_main_id(main_id)
        resource = await db[RESOURCE_COLLECTION].find_one({
            "_id": str(resource_id), "main_id": tenant_id,
        })
        if resource is None:
            return None
        grant = await db[GRANT_COLLECTION].find_one({
            "main_id": tenant_id,
            "resource_type": "personal_knowledge",
            "resource_id": str(resource_id),
            "recipient_user_id": str(user_id),
        })
        if grant is None:
            return None
        if str(grant.get("status") or "") == "dismissed":
            return None
        if resource.get("deleted_at") is None and str(grant.get("status") or "") == "active":
            return None
        return InactiveKnowledgeAccess(resource=resource, grant=grant)

    async def acknowledge(self, *, access: InactiveKnowledgeAccess, user_id: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        db = get_db()
        await db[GRANT_COLLECTION].update_one(
            {"_id": access.grant["_id"]},
            {"$set": {"seen_at": now}},
        )
        await db[FEEDBACK_NOTIFICATION_COLLECTION].update_many({
            "main_id": str(access.resource.get("main_id") or ""),
            "resource_type": "personal_knowledge",
            "resource_id": str(access.resource.get("_id") or ""),
            "recipient_user_id": str(user_id),
            "status": "unread",
        }, {"$set": {"status": "read", "read_at": now}})

    async def dismiss_deleted(self, *, main_id: str, user_id: str, resource_id: str) -> None:
        access = await self.resolve(main_id=main_id, user_id=user_id, resource_id=resource_id)
        if access is None or not access.deleted:
            raise LookupError("knowledge_deleted_record_not_found")
        now = datetime.datetime.now(datetime.timezone.utc)
        await self.acknowledge(access=access, user_id=user_id)
        await get_db()[GRANT_COLLECTION].update_one(
            {"_id": access.grant["_id"]},
            {"$set": {"status": "dismissed", "dismissed_at": now, "seen_at": now, "updated_at": now}},
        )
