"""Resource tenant adapter (021 / 005 / 014 / 015).

Resolves a ``mogo://resource/<subtype>/...`` address into tiered content by
delegating to the **existing** backend stores — no new storage:

* ``doc``  → 005 ``knowledge_document_chunks`` (citation anchor documentId:chunkId)
* ``biz``  → 014 ``business_entity_index`` (entity pointer, fields reused)
* ``kg``   → 015 ``kg_nodes`` via ``TenantKgStore.get_node``

Each tier reuses structured backend fields rather than invoking an LLM (OQ-11):
L0 = label, L1 = structural summary, L2 = the raw detail.
"""

from __future__ import annotations

from typing import Optional

from app.context_space.adapters.base import ResolvedTier, TierAdapter
from app.context_space.address import BIZ, DOC, KG, ResourceAddress
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
    ViewerContext,
    check_visibility,
)
from app.core.db import get_db
from app.core.tenant import add_tenant_scope, resolve_tenant_id


class ResourceTierAdapter(TierAdapter):
    """Resolves resource addresses (doc / biz / kg)."""

    root = "resource"

    async def resolve(
        self,
        *,
        uri: str,
        tier: Optional[str],
        tenant_id: str,
        viewer: ViewerContext,
    ) -> ResolvedTier:
        addr = _parse(uri)
        if tier:
            addr = ResourceAddress(addr.subtype, addr.identifiers, tier)
        if not check_visibility(addr=addr, ctx=viewer):
            raise ContextVisibilityError(f"viewer may not resolve {uri}")

        if addr.subtype == DOC:
            content, meta = await _load_doc(addr, tenant_id)
        elif addr.subtype == BIZ:
            content, meta = await _load_biz(addr, tenant_id)
        else:  # KG
            content, meta = await _load_kg(addr, tenant_id)

        if content is None:
            raise ContextNotFoundError(f"resource not found: {uri}")

        return ResolvedTier(
            uri=addr.uri(),
            tier_used=addr.tier,
            content=content,
            meta=meta or {},
        )


def _parse(uri: str) -> ResourceAddress:
    from app.context_space.address import parse_context_uri

    addr = parse_context_uri(uri)
    if not isinstance(addr, ResourceAddress):
        raise ContextNotFoundError(f"not a resource uri: {uri}")
    return addr


# --- doc (005) --------------------------------------------------------------

async def _load_doc(addr: ResourceAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    tenant_id, document_id, chunk_id = addr.identifiers[0], addr.identifiers[1], addr.identifiers[2]
    db = get_db()
    if db is None:
        return None, {}
    row = await db["knowledge_document_chunks"].find_one(
        {
            "tenant_id": resolve_tenant_id(tenant_id),
            "document_id": document_id,
            "chunk_id": chunk_id,
            "$or": [{"chunk_stage": "rag"}, {"chunk_stage": {"$exists": False}}],
        }
    )
    if row is None:
        return None, {}
    text = str(row.get("text") or "")
    title_path = row.get("titlePath") or []
    title = " / ".join(title_path) if title_path else ""
    contextual = str(row.get("contextualText") or "")
    l0 = (title + " — " + text[:200]).strip() or text[:200]
    l1 = contextual or text[:800]
    l2 = text
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "doc",
        "document_id": document_id,
        "chunk_id": chunk_id,
        "title_path": title_path,
        "page_no": row.get("pageNo"),
        "content_type": row.get("contentType"),
    }


# --- biz (014) --------------------------------------------------------------

async def _load_biz(addr: ResourceAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    tenant_id, system, entity_type, record_id = addr.identifiers
    db = get_db()
    if db is None:
        return None, {}
    # 014 writers have not standardised the stored ``entity_id`` shape, so try the
    # most likely candidates before giving up. We query the existing
    # ``business_entity_index`` collection directly rather than pulling in the
    # heavier BusinessSemanticIndex service (which imports a retrieval client).
    candidates = [
        record_id,
        f"{system}:{entity_type}:{record_id}",
        f"{entity_type}:{record_id}",
    ]
    row = await db["business_entity_index"].find_one(
        {"entity_id": {"$in": candidates}, "tenant_id": tenant_id}
    )
    if row is None:
        return None, {}
    title = str(row.get("title") or "")
    fields = row.get("fields") or {}
    source_ref = str(row.get("source_ref") or "")
    l0 = title or f"{entity_type}:{record_id}"
    l1 = f"type={entity_type} source={source_ref} " + " ".join(
        f"{k}={v}" for k, v in list(fields.items())[:8]
    )
    l2 = str(row.get("content") or "") or l1
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "biz",
        "entity_type": entity_type,
        "entity_id": row.get("entity_id"),
        "title": title,
        "source_ref": source_ref,
    }


# --- kg (015) ---------------------------------------------------------------

async def _load_kg(addr: ResourceAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    tenant_id, node_id = addr.identifiers[0], addr.identifiers[1]
    db = get_db()
    if db is None:
        return None, {}
    from app.knowledge_graph.persisted_store import TenantKgStore

    store = TenantKgStore(tenant_id=tenant_id)
    # Single-node read: do NOT call ``_ensure_loaded()`` (private, and it pulls
    # the tenant's whole graph into memory just to read one node).
    node, neighbours = await store.get_node_direct(node_id)
    if node is None:
        return None, {}
    name = node.name
    entity_type = node.entity_type
    attributes = node.attributes or {}
    l0 = name or node_id
    l1 = f"type={entity_type} neighbours={', '.join(neighbours[:10])}"
    l2 = f"attributes={attributes}"
    content = {"L0": l0, "L1": l1, "L2": l2}.get(addr.tier, l2)
    return content, {
        "subtype": "kg",
        "node_id": node_id,
        "entity_type": entity_type,
        "name": name,
        "source_ref": node.source_ref,
        "neighbour_count": len(neighbours),
    }


__all__ = ["ResourceTierAdapter"]
