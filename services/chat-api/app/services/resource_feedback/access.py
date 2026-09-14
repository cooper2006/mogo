from __future__ import annotations

from dataclasses import dataclass

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.governance.position_policy import MongoEmployeePolicyResolver


@dataclass(frozen=True)
class FeedbackSubject:
    resource_type: str
    resource_id: str
    owner_user_id: str = ""


class FeedbackAccessResolver:
    async def require(self, *, main_id: str, user_id: str, resource_type: str, resource_id: str) -> FeedbackSubject:
        tenant_id = resolve_main_id(main_id)
        kind = str(resource_type or "").strip().lower()
        target_id = str(resource_id or "").strip()
        if kind == "skill_distribution":
            return await self._distribution(tenant_id, str(user_id), target_id)
        if kind == "organization_skill":
            return await self._organization_skill(tenant_id, str(user_id), target_id)
        raise PermissionError("feedback_resource_unsupported")

    async def _distribution(self, main_id: str, user_id: str, resource_id: str) -> FeedbackSubject:
        db = get_db()
        row = await db.skill_distributions.find_one({"_id": resource_id, "main_id": main_id, "status": "active"})
        if row is None:
            raise LookupError("feedback_resource_not_found")
        owner_id = str(row.get("owner_user_id") or "")
        if owner_id != user_id:
            member = await db.skill_distribution_members.find_one({
                "main_id": main_id, "distribution_id": resource_id,
                "recipient_user_id": user_id, "status": "active",
            })
            if member is None:
                raise PermissionError("feedback_forbidden")
        return FeedbackSubject("skill_distribution", resource_id, owner_id)

    async def _organization_skill(self, main_id: str, user_id: str, resource_id: str) -> FeedbackSubject:
        raw_id = resource_id.removeprefix("org_skill:")
        policy = await MongoEmployeePolicyResolver().resolve(main_id, user_id)
        if not policy.allows_skill(raw_id):
            raise PermissionError("feedback_forbidden")
        db = get_db()
        row = await db.skills.find_one({"_id": raw_id, "main_id": main_id})
        if row is None:
            raise LookupError("feedback_resource_not_found")
        return FeedbackSubject("organization_skill", raw_id)
