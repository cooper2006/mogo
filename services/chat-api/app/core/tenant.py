from __future__ import annotations

from typing import Any, Dict


DEFAULT_MAIN_ID = "default"


def resolve_main_id(value: Any = None) -> str:
    tenant_id = str(value or "").strip()
    return tenant_id or DEFAULT_MAIN_ID


def tenant_scope_filter(tenant_id: Any = None) -> Dict[str, Any]:
    """Query scope for a tenant id.

    Phase 3b: the legacy ``main_id`` field has been retired, so the scope is a
    plain equality on ``tenant_id``. The default tenant additionally matches
    documents that never carried a tenant key, preserving the historical
    "unscoped rows belong to the default tenant" semantics.
    """
    resolved = resolve_main_id(tenant_id)
    if resolved == DEFAULT_MAIN_ID:
        return {
            "$or": [
                {"tenant_id": resolved},
                {"tenant_id": {"$exists": False}},
                {"tenant_id": ""},
                {"tenant_id": None},
            ]
        }
    return {"tenant_id": resolved}


def main_scope_filter(tenant_id: Any = None) -> Dict[str, Any]:
    return tenant_scope_filter(tenant_id)


def add_main_scope(query: Dict[str, Any], tenant_id: Any = None) -> Dict[str, Any]:
    base = dict(query or {})
    scope = main_scope_filter(tenant_id)
    if "$or" in scope:
        if not base:
            return scope
        return {"$and": [base, scope]}
    base.update(scope)
    return base
