from __future__ import annotations

from typing import Any, Dict


# Canonical identifier for the default tenant.
DEFAULT_TENANT_ID = "default"


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


__all__ = [
    "DEFAULT_TENANT_ID",
    "add_tenant_scope",
    "resolve_tenant_id",
    "tenant_scope_filter",
]
