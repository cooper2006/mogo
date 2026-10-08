from __future__ import annotations

from typing import Any, Dict


DEFAULT_MAIN_ID = "default"
# Canonical name for the default tenant identifier.
DEFAULT_TENANT_ID = DEFAULT_MAIN_ID


def resolve_tenant_id(value: Any = None) -> str:
    """Normalize a tenant id, falling back to the default tenant."""
    tenant_id = str(value or "").strip()
    return tenant_id or DEFAULT_TENANT_ID


def tenant_scope_filter(tenant_id: Any = None) -> Dict[str, Any]:
    """Query scope for a tenant id.

    The legacy ``main_id`` field has been retired, so the scope is a plain
    equality on ``tenant_id``. The default tenant additionally matches documents
    that never carried a tenant key, preserving the historical "unscoped rows
    belong to the default tenant" semantics.
    """
    resolved = resolve_tenant_id(tenant_id)
    if resolved == DEFAULT_TENANT_ID:
        return {
            "$or": [
                {"tenant_id": resolved},
                {"tenant_id": {"$exists": False}},
                {"tenant_id": ""},
                {"tenant_id": None},
            ]
        }
    return {"tenant_id": resolved}


def add_tenant_scope(query: Dict[str, Any], tenant_id: Any = None) -> Dict[str, Any]:
    base = dict(query or {})
    scope = tenant_scope_filter(tenant_id)
    if "$or" in scope:
        if not base:
            return scope
        return {"$and": [base, scope]}
    base.update(scope)
    return base


# ── Backwards-compatible aliases ───────────────────────────────────────────
# Call sites still import the historical names in ~180 places. They delegate to
# the canonical implementations so behaviour stays identical while new code uses
# the tenant_id naming.
resolve_main_id = resolve_tenant_id
main_scope_filter = tenant_scope_filter
add_main_scope = add_tenant_scope


__all__ = [
    "DEFAULT_MAIN_ID",
    "DEFAULT_TENANT_ID",
    "add_main_scope",
    "add_tenant_scope",
    "main_scope_filter",
    "resolve_main_id",
    "resolve_tenant_id",
    "tenant_scope_filter",
]
