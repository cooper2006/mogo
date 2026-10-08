from __future__ import annotations

from typing import Any

from app.core.db import get_db
from app.core.tenant_identity import PLATFORM_MAIN_ID


def employee_tenant_fields(tenant_id: str, org_name: str) -> dict[str, str]:
    normalized_name = str(org_name or "").strip() or str(tenant_id)
    return {
        "org_name": normalized_name,
        "space_type": "personal" if normalized_name == "个人空间" else "enterprise",
    }


def authoritative_tenant_names(
    organizations: list[dict[str, Any]],
    admin_rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Prefer configured admin identity when billing metadata is stale."""
    names = {
        str(row.get("tenant_id")): str(row.get("org_name") or "").strip()
        for row in organizations
        if str(row.get("org_name") or "").strip()
    }
    names.update({
        str(row.get("tenant_id")): str(row.get("org_name") or "").strip()
        for row in admin_rows
        if str(row.get("org_name") or "").strip()
    })
    return names


async def repair_employee_tenant_identities(db: Any | None = None) -> int:
    database = db if db is not None else get_db()
    excluded = {"$nin": [None, "", "default", PLATFORM_MAIN_ID]}
    # T042: only active tenants are authoritative for identity repair; archived
    # or purged tenants must not resurrect stale organization names.
    active_main_ids = {
        row["tenant_id"]
        async for row in database["tenants"].find(
            {"status": "active", "tenant_id": excluded}, {"tenant_id": 1}
        )
    }
    organizations = [
        row
        async for row in database.organizations.find(
            {"tenant_id": excluded}, {"tenant_id": 1, "org_name": 1}
        )
        if str(row.get("tenant_id")) in active_main_ids
    ]
    admin_rows = [
        row
        async for row in database.admin_accounts.find(
            {"tenant_id": excluded}, {"tenant_id": 1, "org_name": 1}
        )
        if str(row.get("tenant_id")) in active_main_ids
    ]
    names = authoritative_tenant_names(organizations, admin_rows)
    admin_names = authoritative_tenant_names([], admin_rows)
    repaired = 0
    for tenant_id, org_name in names.items():
        fields = employee_tenant_fields(tenant_id, org_name)
        identity_result = await database.end_users.update_many(
            {"tenant_id": tenant_id},
            {"$set": fields},
        )
        repaired += int(identity_result.modified_count)
        if tenant_id in admin_names:
            org_result = await database.organizations.update_many(
                {"tenant_id": tenant_id, "org_name": {"$ne": fields["org_name"]}},
                {"$set": {"org_name": fields["org_name"]}},
            )
            repaired += int(org_result.modified_count)
    return repaired
