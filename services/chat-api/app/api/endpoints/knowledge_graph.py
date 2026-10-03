"""Knowledge graph query endpoint (feature 015).

Minimal production wiring: exposes node lookup and neighbour traversal.
Extraction / mutation endpoints are tracked as follow-ups (FR-1 / FR-10).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: str,
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Return a single KG node (FR-2 / FR-10 minimal query surface)."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.persisted_store import TenantKgStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("main_id") or "")
    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    node = store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node_not_found")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "node_id": node.node_id,
            "entity_type": node.entity_type,
            "name": node.name,
            "attributes": node.attributes,
            "confidence": node.confidence,
            "conflicted": node.conflicted,
            "source_ref": node.source_ref,
        },
    }


@router.get("/nodes/{node_id}/neighbours")
async def get_neighbours(
    node_id: str,
    relation: Optional[str] = None,
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Return outgoing neighbours of a node, optionally filtered by relation type."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.persisted_store import TenantKgStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("main_id") or "")
    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    neighbours = store.neighbours(node_id, relation=relation)
    return {
        "code": 0,
        "message": "ok",
        "data": {"node_id": node_id, "relation": relation, "neighbours": neighbours},
    }


@router.post("/check-constraints")
async def check_constraints(
    payload: dict[str, Any],
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Run the FR-8 constraint checks over the tenant's KG (015 残项修复).

    The request body carries the constraint bundle as plain data:
    ``mutual_exclusions`` (attribute + conflicting_values), ``cardinality``
    (relation + max_per_node) and ``transitive_relations``. Conflicts are
    returned, affected nodes are marked conflicted (FR-14), and the audit
    event flows to the 001 governance stream (kg.audited).
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.consistency import (
        CardinalityRule,
        ConstraintBundle,
        MutualExclusion,
        check_all,
        mark_conflicts,
    )
    from app.knowledge_graph.persisted_store import TenantKgStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("main_id") or "")
    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()

    bundle = ConstraintBundle(
        mutual_exclusions=[
            MutualExclusion(
                attribute=str(item.get("attribute") or ""),
                conflicting_values=[str(v) for v in (item.get("conflicting_values") or [])],
            )
            for item in (payload.get("mutual_exclusions") or [])
        ],
        cardinality=[
            CardinalityRule(
                relation=str(item.get("relation") or ""),
                min_count=int(item.get("min_count") or 0),
                max_count=int(item.get("max_count") or 0),
            )
            for item in (payload.get("cardinality") or [])
        ],
        transitive_relations=[
            str(item) for item in (payload.get("transitive_relations") or [])
        ],
    )
    conflicts = check_all(store, bundle)
    mark_conflicts(store, conflicts)
    await store.persist()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "conflicts": [conflict.as_dict() for conflict in conflicts],
            "total": len(conflicts),
        },
    }


__all__ = ["router"]
