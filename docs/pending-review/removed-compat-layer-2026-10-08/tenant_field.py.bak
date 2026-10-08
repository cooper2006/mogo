"""DEPRECATED (Phase 3b) — retained for historical reference only.

The ``main_id`` -> ``tenant_id`` migration is complete: the legacy field has
been retired from MongoDB and the Weaviate ``mainId`` property. No production
module imports this file any more; call sites read/write ``tenant_id`` (and the
Weaviate ``tenantId`` property) directly. Per the repository's no-delete rule it
is kept in place rather than removed.

Original purpose (Phase 1 dual-write window)
--------------------------------------------
The persisted tenant primary key was historically stored as ``main_id`` (in both
MongoDB collections and the Weaviate ``mainId`` property). Newer code, the
governance layer, and the DSH runtime layer already use ``tenant_id`` /
``tenantId``. To unify without breaking existing data, Phase 1 ran a **dual-write
/ fallback-read** window:

* writers emit BOTH ``main_id`` and ``tenant_id`` (same value);
* readers/queries prefer ``tenant_id`` and fall back to ``main_id`` so documents
  that still only carry ``main_id`` keep working.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

# The canonical persisted key moving forward.
TENANT_ID = "tenant_id"
# The legacy persisted key being retired (Phase 3).
LEGACY_MAIN_ID = "main_id"

# Weaviate / external-schema property names mirror the same split.
TENANT_ID_PROP = "tenantId"
LEGACY_MAIN_ID_PROP = "mainId"


def compose_tenant_fields(value: str) -> Dict[str, str]:
    """Return both persisted tenant keys set to ``value`` for dual-write inserts."""
    value = str(value or "")
    return {TENANT_ID: value, LEGACY_MAIN_ID: value}


def set_tenant_fields(doc: Mapping[str, Any], value: str) -> Dict[str, str]:
    """``$set`` fragment that dual-writes both keys (Phase 2 backfill uses this)."""
    value = str(value or "")
    return {"$set": {TENANT_ID: value, LEGACY_MAIN_ID: value}}


def tenant_value(doc: Mapping[str, Any]) -> str:
    """Read the tenant id from a document, preferring the new key, falling back."""
    if doc is None:
        return ""
    value = doc.get(TENANT_ID)
    if value:
        return str(value)
    legacy = doc.get(LEGACY_MAIN_ID)
    return str(legacy) if legacy else ""


def tenant_scope_filter(tenant_id: Any = None, *, default: str = "default") -> Dict[str, Any]:
    """Query filter matching a tenant on either key.

    Mirrors the historical ``tenant_scope_filter`` semantics but matches both the
    new and legacy key so it works across the dual-write window.
    """
    resolved = str(tenant_id or "").strip() or default
    if resolved == default:
        return {
            "$or": [
                {TENANT_ID: resolved},
                {LEGACY_MAIN_ID: resolved},
                {TENANT_ID: {"$exists": False}},
                {LEGACY_MAIN_ID: {"$exists": False}},
                {TENANT_ID: ""},
                {LEGACY_MAIN_ID: ""},
                {TENANT_ID: None},
                {LEGACY_MAIN_ID: None},
            ]
        }
    return {"$or": [{TENANT_ID: resolved}, {LEGACY_MAIN_ID: resolved}]}


def add_tenant_scope(query: Mapping[str, Any], tenant_id: Any = None, *, default: str = "default") -> Dict[str, Any]:
    """Attach a tenant scope (either key) to ``query`` without clobbering it."""
    base = dict(query or {})
    scope = tenant_scope_filter(tenant_id, default=default)
    if "$or" in scope:
        if not base:
            return scope
        return {"$and": [base, scope]}
    base.update(scope)
    return base


def tenant_query_clauses(tenant_id: Any = None, *, default: str = "default") -> Dict[str, Any]:
    """Backwards-compatible alias used by call sites migrating off ``tenant_scope_filter``."""
    return tenant_scope_filter(tenant_id, default=default)


def dual_write_props(value: str) -> Dict[str, str]:
    """Weaviate-style property dict writing both ``tenantId`` and ``mainId``."""
    value = str(value or "")
    return {TENANT_ID_PROP: value, LEGACY_MAIN_ID_PROP: value}


def tenant_prop_value(doc: Mapping[str, Any]) -> str:
    """Read tenant from a Weaviate-style object, preferring ``tenantId``."""
    if doc is None:
        return ""
    value = doc.get(TENANT_ID_PROP)
    if value:
        return str(value)
    legacy = doc.get(LEGACY_MAIN_ID_PROP)
    return str(legacy) if legacy else ""
