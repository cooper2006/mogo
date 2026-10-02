"""Tenant lifecycle operations at the platform layer (archived / restored / purged).

The ``tenants`` registry row is the source of truth for lifecycle state
(decision 3/15/17). Business data stays in place while a tenant is
*archived* — only the tenant's own ``organizations`` / ``org_quota_policies``
rows flip to ``disabled`` so every in-tenant check short-circuits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.core.db import get_db
from app.core.product_edition import assert_member_limit_settable
from app.core.tenant_identity import is_reserved_main_id
from app.system_audit.repository import SystemAuditRepository
from app.services.tenant_registry import TENANT_COLLECTION

logger = logging.getLogger(__name__)

LIFECYCLE_AUDIT_MODULE = "platform"
LIFECYCLE_AUDIT_MODULE_LABEL = "平台租户管理"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def record_tenant_audit(main_id: str, actor: str, action: str, target: str, result: str, detail: dict[str, Any] | None = None) -> None:
    """Record one tenant lifecycle operation (SC-007).

    Shared by ``tenant_lifecycle`` (archive / restore / update),
    ``tenant_provisioning`` (create) and ``tenant_purge`` (purge) so every
    lifecycle transition is traceable. Audit failures are swallowed: an audit
    outage must never break the transition itself.
    """
    try:
        await SystemAuditRepository().record_management_operation({
            "main_id": main_id,
            "actor": actor,
            "category": "management",
            "module": LIFECYCLE_AUDIT_MODULE,
            "module_label": LIFECYCLE_AUDIT_MODULE_LABEL,
            "action": action,
            "target": target,
            "result": result,
            "details": detail or {},
            "status_code": 0,
        })
    except Exception:  # audit must never break a lifecycle transition
        logger.warning("failed to record lifecycle audit for %s", main_id, exc_info=True)


# Backwards-compatible alias: existing call sites (and tests that monkeypatch
# it) still refer to the private name.
_record_audit = record_tenant_audit


def _validate_main_id(main_id: str) -> str:
    normalized = str(main_id or "").strip()
    if not normalized or len(normalized) < 8 or is_reserved_main_id(normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant identifier")
    return normalized


async def _get_tenant(main_id: str) -> dict[str, Any]:
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"main_id": main_id})
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


async def _get_tenant_by_id(tenant_id: str) -> dict[str, Any]:
    db = get_db()
    tenant = await db[TENANT_COLLECTION].find_one({"_id": tenant_id})
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _status(tenant: dict[str, Any]) -> str:
    return str(tenant.get("status") or "active")


async def _set_tenant_fields(tenant_id: str, fields: dict[str, Any], unset: dict[str, Any] | None = None) -> None:
    db = get_db()
    update: dict[str, Any] = {"$set": {**fields, "updated_at": _utcnow()}}
    if unset:
        update["$unset"] = unset
    await db[TENANT_COLLECTION].update_one({"_id": tenant_id}, update)


async def _set_quota_state(tenant: dict[str, Any], state: str) -> None:
    db = get_db()
    now = _utcnow()
    main_id = tenant["main_id"]
    await db["org_quota_policies"].update_one(
        {"main_id": main_id},
        {"$set": {"status": state, "updated_at": now}},
    )
    await db["organizations"].update_one(
        {"main_id": main_id},
        {"$set": {"status": state, "updated_at": now}},
    )


async def archive_tenant(main_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
    """Soft-archive (T039): data stays intact, login is blocked, the tenant
    stops counting toward licensing (decision 18)."""
    normalized = _validate_main_id(main_id)
    tenant = await _get_tenant(normalized)
    current = _status(tenant)
    if current not in ("active", "disabled"):
        if current in ("archived", "purged"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tenant is already {current}",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant cannot be archived from status '{current}'",
        )

    archived_at = _utcnow()
    archive_reason = reason.strip() or "platform-archive"
    await _set_tenant_fields(
        str(tenant["_id"]),
        {"status": "archived", "archived_at": archived_at, "archive_reason": archive_reason},
    )
    await _set_quota_state(tenant, "disabled")
    await _record_audit(normalized, actor, "archive", normalized, "success", {"reason": archive_reason})
    logger.info("archived tenant %s by %s", normalized, actor)
    return {"mainId": normalized, "status": "archived", "archivedAt": archived_at.isoformat()}


async def restore_tenant(main_id: str, *, actor: str) -> dict[str, Any]:
    """Restore an archived tenant (T041): back to ``active``, data intact."""
    normalized = _validate_main_id(main_id)
    tenant = await _get_tenant(normalized)
    if _status(tenant) != "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only archived tenants can be restored")

    await _set_tenant_fields(
        str(tenant["_id"]),
        {"status": "active", "updated_at": _utcnow()},
        unset={"archived_at": "", "archive_reason": ""},
    )
    await _set_quota_state(tenant, "active")
    await _record_audit(normalized, actor, "restore", normalized, "success")
    return {"mainId": normalized, "status": "active"}


async def update_tenant(
    main_id: str,
    *,
    actor: str,
    name: str | None = None,
    status_target: str | None = None,
    member_limit: int | None | str = None,
) -> dict[str, Any]:
    """PATCH fields (T025): rename, toggle active/disabled, set member limit.

    ``member_limit`` sent as the literal string ``"null"`` clears the cap
    (the wire format cannot express an absent int reliably through all
    front-end tooling, so we accept the string form as well).
    """
    normalized = _validate_main_id(main_id)
    tenant = await _get_tenant(normalized)
    current = _status(tenant)

    fields: dict[str, Any] = {}
    if name is not None:
        clean_name = name.strip()
        if len(clean_name) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must not be empty")
        fields["name"] = clean_name

    if status_target is not None:
        if status_target not in ("active", "disabled"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status must be active or disabled")
        if current not in ("active", "disabled"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lifecycle tenant cannot be enabled/disabled")
        if status_target != current:
            await _set_quota_state(tenant, status_target)
        fields["status"] = status_target

    if member_limit is not None:
        if member_limit == "null":
            fields["member_limit"] = None
        else:
            # Community tenants are unlimited by edition; refuse the cap on the
            # way in instead of writing a value the read side would ignore.
            # Clearing (the "null" branch above) stays allowed.
            await assert_member_limit_settable(normalized)
            try:
                value = int(member_limit)
                if value < 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="memberLimit must be a non-negative integer or null")
            fields["member_limit"] = value

    if not fields:
        return await tenant_view(tenant)

    await _set_tenant_fields(str(tenant["_id"]), fields)
    action = "update"
    detail = {k: v for k, v in fields.items()}
    await _record_audit(normalized, actor, action, normalized, "success", detail)
    updated = await _get_tenant(normalized)
    return await tenant_view(updated)


async def tenant_view(tenant: dict[str, Any]) -> dict[str, Any]:
    """Lifecycle-only view (T027): no member counts, no usage numbers."""
    def fmt(value: Any) -> str:
        if not isinstance(value, datetime):
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    member_limit = tenant.get("member_limit")
    return {
        "mainId": str(tenant.get("main_id") or ""),
        "name": str(tenant.get("name") or ""),
        "status": _status(tenant),
        "edition": str(tenant.get("edition") or "community"),
        "adminUsername": str(tenant.get("admin_username") or ""),
        "memberLimit": int(member_limit) if member_limit is not None else None,
        "createdAt": fmt(tenant.get("created_at")),
        "createdBy": str(tenant.get("created_by") or ""),
        "archivedAt": fmt(tenant.get("archived_at")),
        "archiveReason": str(tenant.get("archive_reason") or ""),
        "purgedAt": fmt(tenant.get("purged_at")),
    }


async def active_tenant_count() -> int:
    """T043/decision 18: the licensing count.

    Only tenants with ``status == "active"`` are counted — disabled and
    archived tenants do not occupy a license slot. The spec (T043) fixes
    the filter to exactly ``{"status": "active"}``.
    """
    db = get_db()
    return await db[TENANT_COLLECTION].count_documents({"status": "active"})
