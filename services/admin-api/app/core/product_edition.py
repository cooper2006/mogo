from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.core.db import get_db

# Layering note: ``core`` importing ``services`` is unusual but deliberate —
# the platform tenant registry (``tenants``) is the authority for a platform
# admin's per-tenant member-cap override, and the capacity gate here must read
# it. ``tenant_registry`` depends only on ``app.core.db`` and
# ``app.core.tenant_identity``, so there is no import cycle.
from app.services.tenant_registry import TENANT_COLLECTION


logger = logging.getLogger(__name__)

COMMUNITY_EDITION = "community"
ORGANIZATION_COLLECTION = "organizations"
SETUP_COLLECTION = "system_bootstrap"
USER_COLLECTION = "end_users"
ORG_QUOTA_COLLECTION = "org_quota_policies"


def is_community_organization(org: dict[str, Any] | None) -> bool:
    if not org:
        return False
    return str(org.get("edition") or org.get("tier") or "").strip().lower() == COMMUNITY_EDITION


def billing_enabled(org: dict[str, Any] | None) -> bool:
    if is_community_organization(org):
        return False
    return bool((org or {}).get("billing_enabled", True))


def member_limit(org: dict[str, Any] | None) -> int | None:
    """Edition-default member cap carried by the tenant's ``organizations`` row.

    This is only the *default*. A platform admin may override it per tenant
    (FR-022) — see :func:`resolve_member_limit`, which is what enforcement and
    every user-facing readout must use.
    """
    if is_community_organization(org):
        return None
    raw_limit = (org or {}).get("user_limit", 5)
    if raw_limit is None:
        return None
    return max(0, int(raw_limit))


async def resolve_member_limit(tenant_id: str, org: dict[str, Any] | None = None) -> int | None:
    """Effective member cap: the platform-set override wins over the edition default.

    FR-022 lets a platform admin set a member cap from the platform console.
    That value lives in ``tenants.member_limit`` (the platform lifecycle
    record), while the edition default lives in ``organizations.user_limit``.
    Reading only the latter would silently ignore the platform setting, so the
    override is resolved here and applied everywhere (capacity gate + dashboard
    readout). A tenant with no registry row, or with an explicitly cleared
    ``member_limit`` (``None``), simply falls back to the edition default —
    which keeps pre-migration deployments and community spaces unlimited.

    **Community is unlimited by edition and the override does not apply**: the
    write-side guard (:func:`assert_member_limit_settable`) refuses to record a
    cap for a community tenant, and this function ignores a stored one for the
    same reason (stale rows written before the guard existed). Both halves are
    needed — a guard alone would leave old data able to contradict the edition.
    """
    db = get_db()
    if org is None:
        org = await db[ORGANIZATION_COLLECTION].find_one({"tenant_id": tenant_id})
    # Community is unlimited by edition; a stored override could only come from
    # before the write-side guard (assert_member_limit_settable) existed. Ignore
    # it rather than let a stale row contradict the edition.
    if is_community_organization(org):
        return None
    tenant = await db[TENANT_COLLECTION].find_one({"tenant_id": tenant_id}, {"member_limit": 1}) or {}
    override = tenant.get("member_limit")
    if override is None:
        return member_limit(org)
    try:
        return max(0, int(override))
    except (TypeError, ValueError):
        logger.warning("ignoring non-numeric tenant member_limit for %s: %r", tenant_id, override)
        return member_limit(org)


async def assert_member_limit_settable(tenant_id: str, org: dict[str, Any] | None = None) -> None:
    """Reject setting a member cap on a tenant whose edition is unlimited.

    Community spaces carry ``user_limit: None`` — meaning *unlimited by
    edition*. FR-022 lets a platform admin cap any tenant, but silently
    applying a cap to an edition that is unlimited by design would make the
    platform console able to contradict the edition, and (worse) would look
    identical to the bug this module already fixed: a setting that is written,
    audited and displayed but whose meaning nobody agreed on.

    So the refusal is explicit and happens **on the way in**: the PATCH fails
    with 409 and the caller is told why, rather than the read side quietly
    ignoring the override. Clearing the cap (``"null"``) is always allowed —
    it restores the edition default, which for community is already unlimited.

    Tenants with no ``organizations`` row are not community
    (:func:`is_community_organization` returns False for a missing row), so a
    pre-migration deployment keeps its previous behaviour.
    """
    if org is None:
        db = get_db()
        org = await db[ORGANIZATION_COLLECTION].find_one({"tenant_id": tenant_id})
    if is_community_organization(org):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="community 版为无限成员版本，不支持设置成员上限",
        )


def community_organization_fields(
    *, tenant_id: str, org_name: str, owner_user_id: str = "", total_points: int = 0
) -> dict[str, Any]:
    return {
        # Phase 1 dual-write: canonical tenant_id + legacy main_id.
        "tenant_id": tenant_id,
        "org_name": org_name or "MOVO 社区组织",
        "edition": COMMUNITY_EDITION,
        "tier": COMMUNITY_EDITION,
        "billing_enabled": False,
        "user_limit": None,
        "is_own_model": True,
        "owner_user_id": str(owner_user_id or ""),
        "total_points": max(0, int(total_points or 0)),
        # T034 / decision 12: community spaces default to unlimited points.
        "points_unlimited": True,
        "updated_at": datetime.now(timezone.utc),
    }


async def ensure_community_organization(
    *, tenant_id: str, org_name: str, owner_user_id: str = "", total_points: int = 0
) -> dict[str, Any]:
    db = get_db()
    now = datetime.now(timezone.utc)
    fields = community_organization_fields(
        tenant_id=tenant_id,
        org_name=org_name,
        owner_user_id=owner_user_id,
        total_points=total_points,
    )
    await db[ORGANIZATION_COLLECTION].update_one(
        {"tenant_id": tenant_id},
        {"$set": fields, "$setOnInsert": {"used_points": 0, "created_at": now}},
        upsert=True,
    )
    return await db[ORGANIZATION_COLLECTION].find_one({"tenant_id": tenant_id}) or fields


async def migrate_bootstrapped_community_organization() -> bool:
    """Mark only the tenant created by the self-hosted setup flow as community."""
    db = get_db()
    state = await db[SETUP_COLLECTION].find_one({"_id": "singleton", "completed": True})
    if not state:
        return False
    tenant_id = str(state.get("tenant_id") or "").strip()
    if not tenant_id:
        return False
    quota = await db[ORG_QUOTA_COLLECTION].find_one({"tenant_id": tenant_id}) or {}
    owner = await db[USER_COLLECTION].find_one({"tenant_id": tenant_id}, {"_id": 1}) or {}
    await ensure_community_organization(
        tenant_id=tenant_id,
        org_name=str(state.get("org_name") or "MOVO 社区组织"),
        owner_user_id=str(owner.get("_id") or ""),
        total_points=int(quota.get("total_tokens") or 0),
    )
    return True


async def count_members(tenant_id: str) -> int:
    """Seats consumed by a tenant — the single source of truth for counting.

    Called by the capacity gate *and* by both display endpoints
    (``dashboard.py`` / ``organizations.py``). They must agree: if the gate
    counts disabled members but the dashboard does not, a tenant at its cap
    would see "3 / 5" while the next create is refused.

    The count deliberately **includes** disabled members. Disabling is a
    reversible state (``directory.py`` re-enables), not a removal — counting
    only active members would let a tenant cycle people through disabled to
    stay under the cap. Deleted members are gone from the collection entirely.
    """
    db = get_db()
    return await db[USER_COLLECTION].count_documents({"tenant_id": tenant_id})


async def assert_member_capacity(tenant_id: str) -> None:
    db = get_db()
    org = await db[ORGANIZATION_COLLECTION].find_one({"tenant_id": tenant_id})
    limit = await resolve_member_limit(tenant_id, org)
    if limit is None:
        return
    current_count = await count_members(tenant_id)
    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前版本最多允许 {limit} 名成员",
        )
