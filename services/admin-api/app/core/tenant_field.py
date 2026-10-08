"""Tenant-identity field compatibility layer during main_id -> tenant_id migration.

Mirror of ``services/chat-api/app/core/tenant_field.py`` for the admin API. The
persisted tenant primary key was historically ``main_id`` (and the Weaviate
property ``mainId``); newer code uses ``tenant_id`` / ``tenantId``. Phase 1 runs
a dual-write / fallback-read window so existing ``main_id`` data keeps working
while writers start emitting ``tenant_id``.

After Phase 2 (backfill) and Phase 3 (retire legacy fields) this module is
deleted and call sites collapse to ``tenant_id``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

TENANT_ID = "tenant_id"
LEGACY_MAIN_ID = "main_id"

TENANT_ID_PROP = "tenantId"
LEGACY_MAIN_ID_PROP = "mainId"


def compose_tenant_fields(value: str) -> Dict[str, str]:
    """Both persisted tenant keys set to ``value`` for dual-write inserts."""
    value = str(value or "")
    return {TENANT_ID: value, LEGACY_MAIN_ID: value}


def tenant_value(doc: Mapping[str, Any] | None) -> str:
    """Read the tenant id preferring the new key, falling back to the legacy one."""
    if doc is None:
        return ""
    value = doc.get(TENANT_ID)
    if value:
        return str(value)
    legacy = doc.get(LEGACY_MAIN_ID)
    return str(legacy) if legacy else ""


def tenant_match(tenant_id: Any) -> Dict[str, Any]:
    """Query fragment matching a tenant on either key (dual-write window).

    .. warning::
        Do **not** pass this into ``sanitize_query_filter`` /
        ``nosql_guard``-protected queries in this service: the guard strips all
        ``$``-prefixed keys (including ``$or``), which would silently drop the
        tenant scope and leak cross-tenant rows. admin-api therefore keeps its
        equality queries on ``main_id`` during Phase 1 (the Phase 2 backfill
        preserves ``main_id``), and only dual-writes on the write paths.
    """
    value = str(tenant_id or "")
    return {"$or": [{TENANT_ID: value}, {LEGACY_MAIN_ID: value}]}


def dual_write_props(value: str) -> Dict[str, str]:
    """Weaviate-style property dict writing both ``tenantId`` and ``mainId``."""
    value = str(value or "")
    return {TENANT_ID_PROP: value, LEGACY_MAIN_ID_PROP: value}
