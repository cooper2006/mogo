"""Harness elastic-config CRUD endpoints (feature 019 FR-7 / FR-9).

* **FR-7** — full CRUD on ``harness_profiles``: list / get / upsert / delete.
* **FR-9** — config authority is constrained to ``full_access_admin`` (006 RBAC);
  all write operations return 403 for non-admin callers.
* **FR-9 audit** — every mutation is logged to the 001 audit stream
  (``harness_profile.changed``) with the full before/after diff.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id

router = APIRouter(prefix="/api/harness-profiles", tags=["harness-config"])

_COLLECTION = "harness_profiles"
_AUDIT_EVENT = "harness_profile.changed"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _require_full_access(db, tenant_id: str, user_id: str) -> None:
    """Raise 403 unless the user holds the tenant's full-access admin role (FR-9)."""
    from app.api.endpoints.dsh_session_versioning import _user_has_full_access

    if not await _user_has_full_access(db, tenant_id, user_id):
        raise HTTPException(status_code=403, detail="FR-9: full_access_admin role required")


def _profile_to_dict(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": doc.get("scope", ""),
        "key": doc.get("key", ""),
        "mode": doc.get("mode", "thick"),
        "enabled_layers": doc.get("enabled_layers"),
        "audit_granularity": doc.get("audit_granularity", ""),
        "timeout_seconds": doc.get("timeout_seconds", 0.0),
        "updated_at": doc.get("updated_at", 0.0),
    }


async def _audit_change(
    db,
    *,
    tenant_id: str,
    user_id: str,
    scope: str,
    key: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    action: str,
) -> None:
    """Write an audit record to the 001 audit stream (best-effort; never blocks
    the main operation)."""
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        diff = {
            k: {"before": before.get(k), "after": (after or {}).get(k)}
            for k in set((before or {}).keys()) | set((after or {}).keys())
        }
        emit_feature_event(
            "019",
            _AUDIT_EVENT,
            {
                "action": action,
                "scope": scope,
                "key": key,
                "user_id": user_id,
                "diff": {k: v for k, v in diff.items() if v["before"] != v["after"]},
            },
        )
    except Exception as exc:
        log_print(f"[harness_profiles] audit event failed: {exc}", flush=True)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_profiles(
    scope: str = "",
    key: str = "",
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """List harness profiles visible to the caller (read-only; any authenticated user)."""
    from app.services.end_user_session import resolve_session_user as _resolve

    resolved = await _resolve(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user", {}).get("_id") or resolved.get("user_id") or "")

    db = get_db()
    if db is None:
        return {"code": 0, "message": "ok", "data": {"profiles": [], "total": 0}}

    query: dict[str, Any] = {}
    if scope:
        query["scope"] = scope
    if key:
        query["key"] = key
    scoped_query = add_tenant_scope(query, tenant_id)
    rows = await db[_COLLECTION].find(scoped_query).to_list(length=500)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "profiles": [_profile_to_dict(r) for r in rows],
            "total": len(rows),
        },
    }


@router.get("/{scope}/{key}")
async def get_profile(
    scope: str,
    key: str,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Fetch a single harness profile by (scope, key)."""
    from app.services.end_user_session import resolve_session_user as _resolve

    resolved = await _resolve(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")

    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db_unavailable")

    row = await db[_COLLECTION].find_one(
        add_tenant_scope({"scope": scope, "key": key}, tenant_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="profile_not_found")
    return {"code": 0, "message": "ok", "data": _profile_to_dict(row)}


@router.put("/{scope}/{key}")
async def upsert_profile(
    scope: str,
    key: str,
    payload: dict[str, Any] = Body(...),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Create or update a harness profile (FR-7 upsert; FR-9 admin-only).

    The ``mode`` field must be either ``thick`` or ``thin``. When a new profile
    is written the FR-8 floor check is enforced server-side (``assert_floor_intact``
    rejects any config that would drop a required layer).
    """
    import time as _time

    from app.harness_config import assert_floor_intact, FloorViolation, resolve_layers, CANONICAL_LAYERS
    from app.services.end_user_session import resolve_session_user as _resolve

    resolved = await _resolve(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user", {}).get("_id") or resolved.get("user_id") or "")

    # FR-9: only full_access_admin may write.
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db_unavailable")
    await _require_full_access(db, tenant_id, user_id)

    mode = str(payload.get("mode") or "thick")
    enabled_layers = payload.get("enabled_layers")
    if mode not in {"thick", "thin"}:
        raise HTTPException(status_code=400, detail="mode must be 'thick' or 'thin'")

    # FR-8 server-side floor check: reject any profile that drops a required layer.
    try:
        effective_layers = resolve_layers(
            mode,
            enabled=list(enabled_layers) if enabled_layers else None,
        )
        assert_floor_intact(enabled_layers=effective_layers, audit_enabled=True)
    except FloorViolation as exc:
        raise HTTPException(status_code=400, detail=f"floor violation: {exc}")

    now = _time.time()
    existing = await db[_COLLECTION].find_one(
        add_tenant_scope({"scope": scope, "key": key}, tenant_id)
    )
    before = _profile_to_dict(existing) if existing else None

    doc: dict[str, Any] = {
        "scope": scope,
        "key": key,
        "mode": mode,
        "enabled_layers": enabled_layers,
        "audit_granularity": str(payload.get("audit_granularity") or ""),
        "timeout_seconds": float(payload.get("timeout_seconds") or 0.0),
        "tenant_id": tenant_id,
        "updated_at": now,
        "updated_by": user_id,
    }
    result = await db[_COLLECTION].replace_one(
        add_tenant_scope({"scope": scope, "key": key}, tenant_id),
        doc,
        upsert=True,
    )
    after = _profile_to_dict(doc)

    await _audit_change(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope=scope,
        key=key,
        before=before,
        after=after,
        action="create" if before is None else "update",
    )
    return {"code": 0, "message": "ok", "data": after}


@router.delete("/{scope}/{key}")
async def delete_profile(
    scope: str,
    key: str,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Delete a harness profile (FR-7; FR-9 admin-only)."""
    from app.services.end_user_session import resolve_session_user as _resolve

    resolved = await _resolve(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")
    user_id = str(resolved.get("user", {}).get("_id") or resolved.get("user_id") or "")

    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db_unavailable")
    await _require_full_access(db, tenant_id, user_id)

    existing = await db[_COLLECTION].find_one(
        add_tenant_scope({"scope": scope, "key": key}, tenant_id)
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="profile_not_found")

    result = await db[_COLLECTION].delete_one(
        add_tenant_scope({"scope": scope, "key": key}, tenant_id)
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="profile_not_found")

    await _audit_change(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        scope=scope,
        key=key,
        before=_profile_to_dict(existing),
        after=None,
        action="delete",
    )
    return {"code": 0, "message": "deleted"}


__all__ = ["router"]
