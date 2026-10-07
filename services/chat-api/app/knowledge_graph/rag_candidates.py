"""KG-assisted RAG candidates (015 residual: RAG 接入).

Mirrors the 017 ``memory_rag_candidates`` pattern: surface KG entity context
(typename + neighbours + relations) as ranked candidates that the RAG
retrieval pass can inject alongside document chunks. This gives the LLM
grounding in the tenant's business entity graph without a separate 015
retrieval path.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from typing import Any, Optional

from app.knowledge_graph.persisted_store import TenantKgStore


async def kg_rag_candidates(
    *,
    tenant_id: str,
    entity_terms: list[str],
    top_n: int = 4,
) -> list[dict[str, Any]]:
    """Return KG entity context for ``entity_terms`` as RAG candidates.

    For each term that matches (case-insensitive) a KG node name or id, the
    candidate carries:
    * ``entity_id`` / ``entity_type`` / ``name``;
    * ``source_ref`` (the 014 pointer, when present);
    * ``neighbours`` — the first ``top_n`` outgoing neighbours;
    * ``context_text`` — a one-line summary suitable for prompt injection.

    Terms that do not match any node are skipped (never fabricated).
    """
    if not entity_terms:
        return []

    try:
        store = TenantKgStore(tenant_id=tenant_id)
        await store._ensure_loaded()
    except Exception as exc:
        log_print(f"[knowledge_graph.rag_candidates] silent exception caught: {exc}", flush=True)
        return []

    # Build a case-insensitive lookup.
    lookup: dict[str, str] = {}
    for node_id, node in store.nodes.items():
        lookup[node_id.lower()] = node_id
        if node.name:
            lookup[node.name.lower()] = node_id

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in entity_terms:
        key = str(term).lower()
        matched = lookup.get(key)
        if matched is None or matched in seen:
            continue
        seen.add(matched)
        node = store.get_node(matched)
        if node is None:
            continue
        neighbours = store.neighbours(matched)[:top_n]
        context_text = (
            f"Entity {node.name!r} ({node.entity_type})"
            + (f", source_ref={node.source_ref!r}" if node.source_ref else "")
            + (f", related to: {', '.join(neighbours)}" if neighbours else "")
        )
        candidates.append({
            "entity_id": matched,
            "entity_type": node.entity_type,
            "name": node.name,
            "source_ref": node.source_ref,
            "neighbours": neighbours,
            "context_text": context_text,
        })
        if len(candidates) >= top_n:
            break

    return candidates


__all__ = ["kg_rag_candidates"]
