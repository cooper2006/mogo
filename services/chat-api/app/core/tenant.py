from __future__ import annotations

from typing import Any, Dict


DEFAULT_MAIN_ID = "default"


def resolve_main_id(value: Any = None) -> str:
    main_id = str(value or "").strip()
    return main_id or DEFAULT_MAIN_ID


def main_scope_filter(main_id: Any = None) -> Dict[str, Any]:
    # Phase 1 of the main_id -> tenant_id migration: the legacy ``main_id`` key
    # and the new ``tenant_id`` key coexist. Match either so documents written
    # before/after the backfill both resolve. See core/tenant_field.py.
    from app.core.tenant_field import tenant_scope_filter

    return tenant_scope_filter(main_id, default=DEFAULT_MAIN_ID)


def add_main_scope(query: Dict[str, Any], main_id: Any = None) -> Dict[str, Any]:
    base = dict(query or {})
    scope = main_scope_filter(main_id)
    if "$or" in scope:
        if not base:
            return scope
        return {"$and": [base, scope]}
    base.update(scope)
    return base
