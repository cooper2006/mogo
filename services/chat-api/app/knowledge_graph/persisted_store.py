"""MongoDB-backed knowledge graph store (015 FR-10 / minimal wiring).

Mirrors the in-memory KgStore; persistence uses kg_nodes and kg_edges
collections, both tenant-scoped.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.knowledge_graph.schema import KgEdge, KgNode, DEFAULT_CONFIDENCE_FLOOR
from app.knowledge_graph.store import merge_nodes

COLLECTION_NODES = "kg_nodes"
COLLECTION_EDGES = "kg_edges"


def _node_to_doc(node: KgNode) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "entity_type": node.entity_type,
        "name": node.name,
        "attributes": node.attributes,
        "source_ref": node.source_ref,
        "confidence": node.confidence,
        "conflicted": node.conflicted,
    }


def _doc_to_node(doc: dict[str, Any]) -> KgNode:
    return KgNode(
        node_id=str(doc.get("node_id") or ""),
        entity_type=str(doc.get("entity_type") or "person"),
        name=str(doc.get("name") or ""),
        attributes=dict(doc.get("attributes") or {}),
        source_ref=str(doc.get("source_ref") or ""),
        confidence=float(doc.get("confidence") or 1.0),
        conflicted=bool(doc.get("conflicted") or False),
    )


def _edge_to_doc(edge: KgEdge) -> dict[str, Any]:
    return {
        "source": edge.source,
        "target": edge.target,
        "relation": edge.relation,
        "attributes": edge.attributes,
        "confidence": edge.confidence,
    }


class TenantKgStore:
    """Tenant-scoped MongoDB-backed KG store with lazy load."""

    def __init__(self, *, tenant_id: str, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR):
        self._tenant_id = resolve_main_id(tenant_id)
        self._floor = confidence_floor
        self._nodes: dict[str, KgNode] = {}
        self._edges: dict[str, list[KgEdge]] = {}
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        db = get_db()
        if db is None:
            return
        rows = await db[COLLECTION_NODES].find({"tenant_id": self._tenant_id}).to_list(length=2000)
        for row in rows:
            node = _doc_to_node(row)
            self._nodes[node.node_id] = node
        edge_rows = await db[COLLECTION_EDGES].find({"tenant_id": self._tenant_id}).to_list(length=5000)
        for row in edge_rows:
            edge = KgEdge(
                source=str(row.get("source") or ""),
                target=str(row.get("target") or ""),
                relation=str(row.get("relation") or "association"),
                attributes=dict(row.get("attributes") or {}),
                confidence=float(row.get("confidence") or 1.0),
            )
            self._edges.setdefault(edge.source, []).append(edge)

    def add_node(self, node: KgNode) -> bool:
        if node.confidence < self._floor:
            return False
        existing = self._nodes.get(node.node_id)
        if existing is None:
            self._nodes[node.node_id] = node
        else:
            self._nodes[node.node_id] = merge_nodes(existing, node)
        return True

    def add_edge(self, edge: KgEdge) -> bool:
        if edge.confidence < self._floor:
            return False
        if edge.source not in self._nodes or edge.target not in self._nodes:
            return False
        self._edges.setdefault(edge.source, []).append(edge)
        return True

    def neighbours(self, node_id: str, *, relation: Optional[str] = None) -> list[str]:
        edges = self._edges.get(node_id, [])
        if relation:
            edges = [e for e in edges if e.relation == relation]
        return [e.target for e in edges]

    def get_node(self, node_id: str) -> Optional[KgNode]:
        return self._nodes.get(node_id)

    def __len__(self) -> int:
        return len(self._nodes)

    async def persist(self) -> None:
        db = get_db()
        if db is None:
            return
        for node in self._nodes.values():
            doc = _node_to_doc(node)
            doc["tenant_id"] = self._tenant_id
            await db[COLLECTION_NODES].replace_one(
                {"node_id": node.node_id, "tenant_id": self._tenant_id},
                doc,
                upsert=True,
            )
        for source, edges in self._edges.items():
            for edge in edges:
                doc = _edge_to_doc(edge)
                doc["tenant_id"] = self._tenant_id
                await db[COLLECTION_EDGES].replace_one(
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "relation": edge.relation,
                        "tenant_id": self._tenant_id,
                    },
                    doc,
                    upsert=True,
                )
