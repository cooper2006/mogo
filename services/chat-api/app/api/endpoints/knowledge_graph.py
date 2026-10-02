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


__all__ = ["router"]
