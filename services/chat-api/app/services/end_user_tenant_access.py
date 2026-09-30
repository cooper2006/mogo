from __future__ import annotations

from typing import Any, Iterable

from app.core.product_edition import product_edition_fields


def resolve_space_type(user: dict[str, Any], organization: dict[str, Any] | None = None) -> str:
    explicit = str(user.get("space_type") or "").strip().lower()
    if explicit in {"personal", "enterprise"}:
        return explicit
    org_name = str((organization or {}).get("org_name") or user.get("org_name") or "").strip()
    return "personal" if org_name == "个人空间" else "enterprise"


def resolve_org_name(user: dict[str, Any], organization: dict[str, Any] | None = None) -> str:
    """Resolve a display name without letting stale personal-space data mask an enterprise."""
    user_org_name = str(user.get("org_name") or "").strip()
    stored_org_name = str((organization or {}).get("org_name") or "").strip()
    explicit_space_type = str(user.get("space_type") or "").strip().lower()

    if (
        explicit_space_type == "enterprise"
        and user_org_name
        and user_org_name != "个人空间"
        and stored_org_name == "个人空间"
    ):
        return user_org_name
    return stored_org_name or user_org_name or str(user.get("main_id") or "").strip()


def project_tenant_candidate(
    user: dict[str, Any],
    organization: dict[str, Any] | None,
    admin_account: dict[str, Any] | None,
) -> dict[str, Any]:
    main_id = str(user.get("main_id") or "").strip()
    org_name = resolve_org_name(user, organization) or main_id
    space_type = resolve_space_type(user, organization)
    can_access_admin = bool(
        space_type == "enterprise"
        and
        admin_account
        and admin_account.get("status") == "active"
        and str(admin_account.get("group_code") or "") != "member"
    )
    return {
        "mainId": main_id,
        "orgName": org_name,
        "spaceType": space_type,
        "userId": str(user.get("_id") or ""),
        "displayName": str(user.get("name") or user.get("login_name") or ""),
        "username": str(user.get("login_name") or ""),
        "canAccessAdmin": can_access_admin,
        **product_edition_fields(organization),
    }


async def load_tenant_candidates(db: Any, users: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    user_rows = list(users)
    main_ids = sorted({str(row.get("main_id") or "").strip() for row in user_rows if row.get("main_id")})
    organizations = await db.organizations.find({"main_id": {"$in": main_ids}}).to_list(length=max(1, len(main_ids))) if main_ids else []
    admin_accounts = await db.admin_accounts.find({
        "main_id": {"$in": main_ids}, "status": "active",
    }).to_list(length=max(1, len(main_ids) * 100)) if main_ids else []
    organization_by_tenant = {str(row.get("main_id") or ""): row for row in organizations}
    for account in admin_accounts:
        main_id = str(account.get("main_id") or "")
        if main_id not in organization_by_tenant and str(account.get("org_name") or "").strip():
            organization_by_tenant[main_id] = {
                "main_id": main_id,
                "org_name": str(account.get("org_name") or "").strip(),
            }
    admin_by_identity = {(str(row.get("main_id") or ""), str(row.get("username") or "")): row for row in admin_accounts}
    # FR-024: a tenant that is no longer active must not be selectable. The
    # ``tenants`` registry is owned by admin-api but lives in the same database,
    # so read it directly rather than trusting the derived organization status.
    active_main_ids = await _selectable_tenant_main_ids(db, main_ids)
    return [
        project_tenant_candidate(
            row,
            organization_by_tenant.get(str(row.get("main_id") or "")),
            admin_by_identity.get((str(row.get("main_id") or ""), str(row.get("login_name") or ""))),
        )
        for row in user_rows
        if str(row.get("main_id") or "").strip() in active_main_ids
    ]


async def is_tenant_selectable(db: Any, main_id: str) -> bool:
    """Whether ``main_id`` may be entered right now (FR-024)."""
    return str(main_id or "").strip() in await _selectable_tenant_main_ids(db, [str(main_id or "").strip()])


async def _selectable_tenant_main_ids(db: Any, main_ids: list[str]) -> set[str]:
    """Subset of ``main_ids`` whose registry row is ``active`` (FR-024).

    Only ``active`` passes for a tenant that has a registry row. Tenants with
    *no* registry row are grandfathered in: a deployment that has not run the
    020 migration yet has an empty ``tenants`` collection, and failing closed
    there would lock every employee out.
    """
    if not main_ids:
        return set()
    rows = await db["tenants"].find(
        {"main_id": {"$in": main_ids}}, {"main_id": 1, "status": 1}
    ).to_list(length=max(1, len(main_ids)))
    active = {str(row.get("main_id") or "").strip() for row in rows if str(row.get("status") or "") == "active"}
    known = {str(row.get("main_id") or "").strip() for row in rows}
    return active | {main_id for main_id in main_ids if main_id not in known}
