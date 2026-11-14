"""Permission-code grant management (T024, US4).

Fine-grained permission codes (`<resource>:<action>[:<target>]`) are granted to
tenants, organizations, and users in a three-level isolation model (US4):

=====================  =================================
level                 scope
=====================  =================================
tenant                every user in the tenant
org                   users within one organization
user                  a single user
=====================  =================================

Grants live in the ``permission_grants`` collection and take effect
immediately: the ``rbac_model`` resolution path unions *position-role preset
groups* (006, T009) with *explicit grants* from this store, so changing a
grant is reflected on the next tool call without any cache or redeploy.
Revocation works the same way (remove the grant -> code no longer resolves).

Grant mutations are audited through the single audit sink
(``gate_events`` via :func:`audit_permission_change`, FR-9).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .rbac_model import PermissionCode, parse_codes

PERMISSION_GRANTS_COLLECTION = "permission_grants"

GRANT_LEVELS: tuple[str, ...] = ("tenant", "org", "user")


def _get_db() -> Any:
    from app.core.db import get_db

    return get_db()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_code(raw: str) -> str:
    """Normalize + validate a permission code (fail-closed on malformed input)."""
    try:
        return str(PermissionCode.parse(raw))
    except ValueError as exc:
        raise ValueError(f"invalid permission code {raw!r}: {exc}") from exc


async def grant_code(
    *,
    tenant_id: str,
    code: str,
    level: str = "user",
    org_id: str = "",
    user_id: str = "",
    granted_by: str = "",
) -> dict[str, Any]:
    """Grant a permission code at one isolation level.

    * ``tenant``: grants to the whole tenant (``tenant_id`` required).
    * ``org``: grants to one organization (``tenant_id`` + ``org_id``).
    * ``user``: grants to one user (``tenant_id`` + ``user_id``).

    Idempotent: re-granting the same scope replaces the document (keeps the
    single-audit-sink semantics simple and the change visible).
    """
    if level not in GRANT_LEVELS:
        raise ValueError(f"unknown grant level: {level!r}")
    if not tenant_id:
        raise ValueError("tenant_id is required for permission grants")
    if level == "org" and not org_id:
        raise ValueError("org_id is required for org-level grants")
    if level == "user" and not user_id:
        raise ValueError("user_id is required for user-level grants")
    normalized = _validate_code(code)

    db = _get_db()
    document = {
        "tenant_id": tenant_id,
        "level": level,
        "org_id": org_id,
        "user_id": user_id,
        "code": normalized,
        "granted_by": granted_by,
        "granted_at": _utcnow(),
    }
    await db[PERMISSION_GRANTS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "level": level, "org_id": org_id, "user_id": user_id, "code": normalized},
        {"$set": document},
        upsert=True,
    )
    await audit_permission_change(actor=granted_by or "system", action="grant", tenant_id=tenant_id, code=normalized, scope={"level": level, "org_id": org_id, "user_id": user_id})
    return document


async def revoke_code(
    *,
    tenant_id: str,
    code: str,
    level: str = "user",
    org_id: str = "",
    user_id: str = "",
    revoked_by: str = "",
) -> bool:
    """Revoke one explicit grant (takes effect on the next evaluation)."""
    normalized = _validate_code(code)
    db = _get_db()
    result = await db[PERMISSION_GRANTS_COLLECTION].delete_one(
        {"tenant_id": tenant_id, "level": level, "org_id": org_id, "user_id": user_id, "code": normalized}
    )
    if result.deleted_count:
        await audit_permission_change(actor=revoked_by or "system", action="revoke", tenant_id=tenant_id, code=normalized, scope={"level": level, "org_id": org_id, "user_id": user_id})
    return bool(result.deleted_count)


async def list_grants(*, tenant_id: str, level: str = "", code: str = "") -> list[dict[str, Any]]:
    """List the tenant's explicit grants, optionally filtered."""
    db = _get_db()
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if level:
        query["level"] = level
    if code:
        query["code"] = _validate_code(code)
    cursor = db[PERMISSION_GRANTS_COLLECTION].find(query).sort([("level", 1), ("code", 1)])
    return [doc async for doc in cursor]


async def effective_grant_codes(*, tenant_id: str, org_id: str = "", user_id: str = "") -> set[str]:
    """Union of the subject's explicit grants across all three levels.

    A user sees tenant + org + user grants; an org (no user) sees tenant + org.
    Degrades to an empty set when the store is unreachable (fail-closed at the
    RBAC layer, which denies when no code resolves — matching the 006
    semantics, no widening on error).
    """
    try:
        db = _get_db()
    except Exception:
        return set()
    scopes: list[dict[str, Any]] = [{"tenant_id": tenant_id, "level": "tenant"}]
    if org_id:
        scopes.append({"tenant_id": tenant_id, "level": "org", "org_id": org_id})
    if user_id:
        scopes.append({"tenant_id": tenant_id, "level": "user", "user_id": user_id})
    codes: set[str] = set()
    for scope in scopes:
        cursor = db[PERMISSION_GRANTS_COLLECTION].find(scope)
        for doc in await cursor.to_list(length=10_000):
            codes.add(doc.get("code", ""))
    return {c for c in codes if c}


async def audit_permission_change(
    *, actor: str, action: str, tenant_id: str, code: str, scope: Optional[dict[str, Any]] = None
) -> None:
    """Record a grant/revoke in the single audit sink (gate_events, FR-9 / T024)."""
    from .layers.audit import GATE_EVENTS_COLLECTION

    try:
        db = _get_db()
        await db[GATE_EVENTS_COLLECTION].insert_one(
            {
                "event_id": uuid.uuid4().hex,
                "occurred_at": _utcnow(),
                "tenant_id": tenant_id,
                "user_id": actor,
                "roles": [],
                "tool": f"gate.permissions.{action}",
                "risk_level": "",
                "autonomy_level": "",
                "decision": "allow",
                "layer": "permission_admin",
                "reason": f"permission code {action}: {code}",
                "detail": {"code": code, "action": action, "scope": scope or {}},
            }
        )
    except Exception:
        pass


async def ensure_permission_indexes() -> None:
    from app.core.db import get_db

    db = get_db()
    await db[PERMISSION_GRANTS_COLLECTION].create_index(
        [("tenant_id", 1), ("level", 1), ("org_id", 1), ("user_id", 1), ("code", 1)],
        name="permission_grant_key",
        unique=True,
    )
