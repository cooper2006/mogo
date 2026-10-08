"""Knowledge graph query + mutation endpoint (feature 015).

* FR-2 / FR-10 — node lookup and neighbour traversal;
* FR-1 — extraction endpoint (structured record or free text → typed entities);
* FR-8 — constraint checks over the tenant's KG;
* FR-13 — ``source_ref`` pointer read/write: a KG node may reference a 014
  business entity by pointer (never a copy); ``GET .../resolve`` follows the
  pointer into the 014 index.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

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
    tenant_id = str(resolved.get("tenant_id") or "")
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
    tenant_id = str(resolved.get("tenant_id") or "")
    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    neighbours = store.neighbours(node_id, relation=relation)
    return {
        "code": 0,
        "message": "ok",
        "data": {"node_id": node_id, "relation": relation, "neighbours": neighbours},
    }


# ---------------------------------------------------------------------------
# FR-1: extraction endpoint
# ---------------------------------------------------------------------------


@router.post("/extract")
async def extract_kg(
    payload: dict[str, Any],
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Extract typed entities/relations into the tenant's KG (015 FR-1).

    The body is a structured record (dict) or a free-text string (``text`` field).
    Extraction is rule-based (no LLM); low-confidence results below the floor
    are rejected. Returns the written counts and the extracted shapes.
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.extract import extract, apply_to_store
    from app.knowledge_graph.persisted_store import TenantKgStore

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")

    record: Any
    if isinstance(payload.get("text"), str):
        record = str(payload.get("text"))
    elif isinstance(payload.get("record"), dict):
        record = dict(payload.get("record"))
    else:
        record = payload

    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    result = extract(record)
    counts = apply_to_store(store, record)
    await store.persist()

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "nodes_added": counts["nodes_added"],
            "edges_added": counts["edges_added"],
            "result": result.as_dicts(),
        },
    }


# ---------------------------------------------------------------------------
# FR-13: source_ref pointer read/write
# ---------------------------------------------------------------------------


@router.post("/nodes")
async def upsert_node(
    payload: dict[str, Any],
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Create / merge a KG node, optionally carrying a 014 ``source_ref``
    pointer (FR-13: reference by pointer, never copy the entity data)."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.persisted_store import TenantKgStore
    from app.knowledge_graph.schema import KgNode, ENTITY_TYPES

    resolved = await _resolve_session_user(authorization)
    tenant_id = str(resolved.get("tenant_id") or "")

    node_id = str(payload.get("node_id") or "").strip()
    if not node_id:
        raise HTTPException(status_code=400, detail="node_id is required")
    entity_type = str(payload.get("entity_type") or "person")
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown entity_type: {entity_type!r}")

    node = KgNode(
        node_id=node_id,
        entity_type=entity_type,
        name=str(payload.get("name") or ""),
        attributes=dict(payload.get("attributes") or {}),
        source_ref=str(payload.get("source_ref") or ""),
        confidence=float(payload.get("confidence") or 1.0),
    )

    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    if not store.add_node(node):
        raise HTTPException(status_code=422, detail="node_rejected (confidence below floor)")
    await store.persist()

    return {
        "code": 0,
        "message": "ok",
        "data": {"node_id": node_id, "source_ref": node.source_ref},
    }


@router.get("/nodes/{node_id}/resolve")
async def resolve_source_ref(
    node_id: str,
    *,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Follow the node's ``source_ref`` pointer into the 014 business index
    (FR-13). Returns the referenced record without copying it; ``resolved``
    is False when the pointer is empty or the target does not exist."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.knowledge_graph.persisted_store import TenantKgStore

    resolved_user = await _resolve_session_user(authorization)
    tenant_id = str(resolved_user.get("tenant_id") or "")

    store = TenantKgStore(tenant_id=tenant_id)
    await store._ensure_loaded()
    node = store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node_not_found")
    if not node.source_ref:
        return {"code": 0, "message": "ok", "data": {"resolved": False, "reason": "no_source_ref"}}

    # Follow the pointer into the 014 semantic index (biz_entities collection).
    try:
        from app.core.db import get_db
        db = get_db()
        row = await db["biz_entities"].find_one({
            "entity_id": node.source_ref,
            "tenant_id": tenant_id,
        })
    except Exception as exc:
        log_print(f"[api.endpoints.knowledge_graph.resolve_source_ref] suppressed {type(exc).__name__}: {exc}", flush=True)
        row = None
    if row is None:
        return {"code": 0, "message": "ok", "data": {"resolved": False, "reason": "pointer_target_missing"}}
    return {
        "code": 0,
        "message": "ok",
        "data": {"resolved": True, "entity_id": node.source_ref, "entity": row},
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
    tenant_id = str(resolved.get("tenant_id") or "")
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
