from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.core.db import get_db

MIGRATION_COLLECTION = "position_role_migrations"

CAPABILITY_KEYS = (
    "content_generation",
    "image_generation",
    "code_generation",
    "browser_automation",
    "internal_knowledge",
)

INTERNAL_CAPABILITY_REQUIREMENTS = {
    "content.produce@v1": "content_generation",
    "presentation.create@v1": "content_generation",
    "document.pdf_retain_pages@v1": "content_generation",
    "image.generate@v1": "image_generation",
    "browser.task@v1": "browser_automation",
    "knowledge.search@v1": "internal_knowledge",
    "knowledge.read_document@v1": "internal_knowledge",
}


@dataclass(frozen=True)
class EffectiveEmployeePolicy:
    tenant_id: str
    user_id: str
    capabilities: dict[str, bool]
    role_ids: tuple[str, ...] = ()
    role_names: tuple[str, ...] = ()
    migration_pending: bool = False
    version: str = ""

    def allows_capability(self, key: str) -> bool:
        return bool(self.capabilities.get(key, False))

    def allows_internal(self, capability_ref: str) -> bool:
        required = INTERNAL_CAPABILITY_REQUIREMENTS.get(capability_ref)
        return required is None or self.allows_capability(required)

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "capabilities": dict(self.capabilities),
            "roleIds": list(self.role_ids),
            "roleNames": list(self.role_names),
            "migrationPending": self.migration_pending,
            "version": self.version,
        }


class EmployeePolicyResolver(Protocol):
    async def resolve(self, tenant_id: str, user_id: str) -> EffectiveEmployeePolicy: ...


class MongoEmployeePolicyResolver:
    async def resolve(self, tenant_id: str, user_id: str) -> EffectiveEmployeePolicy:
        db = get_db()
        assignments = await db.end_user_position_roles.find(
            {"tenant_id": tenant_id, "user_id": user_id}
        ).to_list(length=100)
        role_ids = [str(row.get("role_id") or "") for row in assignments if row.get("role_id")]
        roles = await db.position_roles.find(
            {"tenant_id": tenant_id, "_id": {"$in": role_ids}, "status": "active"}
        ).to_list(length=100) if role_ids else []

        now = datetime.now(timezone.utc)
        overrides = await db.end_user_capability_overrides.find({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": "active",
            "effective_at": {"$lte": now},
            "$or": [{"expires_at": None}, {"expires_at": {"$exists": False}}, {"expires_at": {"$gt": now}}],
        }).sort("created_at", 1).to_list(length=100)
        migration = await db[MIGRATION_COLLECTION].find_one({"tenant_id": tenant_id}, {"status": 1})
        return build_effective_policy(
            tenant_id,
            user_id,
            roles,
            overrides,
            role_ids,
            migration_completed=str((migration or {}).get("status") or "pending") == "complete",
        )


def build_effective_policy(
    tenant_id: str,
    user_id: str,
    roles: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None = None,
    assigned_role_ids: list[str] | None = None,
    migration_completed: bool = False,
) -> EffectiveEmployeePolicy:
    if not roles and not assigned_role_ids:
        if migration_completed:
            return EffectiveEmployeePolicy(
                tenant_id=tenant_id,
                user_id=user_id,
                capabilities={key: False for key in CAPABILITY_KEYS},
                migration_pending=False,
                version="migration-complete-no-role",
            )
        return EffectiveEmployeePolicy(
            tenant_id=tenant_id,
            user_id=user_id,
            capabilities={key: True for key in CAPABILITY_KEYS},
            migration_pending=True,
            version="legacy-full-access",
        )

    capabilities = {key: False for key in CAPABILITY_KEYS}
    allowed_capabilities: set[str] = set()
    denied_capabilities: set[str] = set()
    role_names: list[str] = []
    version_parts: list[str] = []
    role_ids = list(assigned_role_ids or [str(role.get("_id") or "") for role in roles])

    for role in roles:
        role_names.append(str(role.get("name") or ""))
        for key in CAPABILITY_KEYS:
            capabilities[key] = capabilities[key] or bool((role.get("capabilities") or {}).get(key))
        version_parts.append(f"{role.get('_id')}:{_timestamp(role.get('updated_at'))}")

    for override in overrides or []:
        allowed_capabilities.update(str(key) for key in override.get("allow_capabilities") or [])
        denied_capabilities.update(str(key) for key in override.get("deny_capabilities") or [])
        version_parts.append(f"override:{override.get('_id')}:{_timestamp(override.get('updated_at'))}")

    for key in allowed_capabilities:
        if key in capabilities:
            capabilities[key] = True
    for key in denied_capabilities:
        if key in capabilities:
            capabilities[key] = False

    return EffectiveEmployeePolicy(
        tenant_id=tenant_id,
        user_id=user_id,
        capabilities=capabilities,
        role_ids=tuple(role_ids),
        role_names=tuple(role_names),
        version="|".join(version_parts),
    )


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")
