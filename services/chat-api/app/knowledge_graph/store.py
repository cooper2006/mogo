"""Adjacency store + merge semantics (015 FR-2 / FR-3).

First delivery uses an in-memory adjacency structure (the Mongo-backed version
mirrors it). Merging follows the clarify rule: same-entity attributes from multiple
sources are **merged, never overwritten**; a conflicting attribute is kept as
multiple values and the node is flagged ``conflicted`` (FR-3).
"""

from __future__ import annotations

from typing import Any

from .schema import DEFAULT_CONFIDENCE_FLOOR, KgEdge, KgNode


def _audit_kg_mutation(entity: Any) -> None:
    """Emit a ``015 kg.mutated`` event through the T999 bridge (fire-and-forget)."""
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        if isinstance(entity, KgNode):
            emit_feature_event(
                "015",
                "kg.mutated",
                {
                    "node_id": entity.node_id,
                    "entity_type": entity.entity_type,
                    "confidence": entity.confidence,
                },
            )
        elif isinstance(entity, KgEdge):
            emit_feature_event(
                "015",
                "kg.mutated",
                {
                    "edge": f"{entity.source}->{entity.target}",
                    "relation": entity.relation,
                    "confidence": entity.confidence,
                },
            )
    except Exception:
        # 审计失败绝不影响主流程（fail-open for audit; KG writes are unaffected）。
        pass


def merge_nodes(existing: KgNode, incoming: KgNode) -> KgNode:
    """Merge ``incoming`` into ``existing`` without overwriting values (FR-3).

    * attributes present in both with different values -> kept as a list of values
      and the node is marked ``conflicted``;
    * ``source_ref`` is preserved if either side has one;
    * confidence keeps the maximum.
    """
    merged_attributes: dict[str, Any] = dict(existing.attributes)
    conflicted = existing.conflicted
    for key, value in incoming.attributes.items():
        if key not in merged_attributes:
            merged_attributes[key] = value
            continue
        current = merged_attributes[key]
        if current == value:
            continue
        # Conflicting values: keep both, flag the node.
        bucket = list(current) if isinstance(current, list) else [current]
        if value not in bucket:
            bucket.append(value)
        merged_attributes[key] = bucket
        conflicted = True

    return KgNode(
        node_id=existing.node_id,
        entity_type=existing.entity_type,
        name=existing.name or incoming.name,
        attributes=merged_attributes,
        source_ref=existing.source_ref or incoming.source_ref,
        confidence=max(existing.confidence, incoming.confidence),
        conflicted=conflicted,
    )


class KgStore:
    """In-memory adjacency graph store."""

    def __init__(self, *, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR) -> None:
        self.nodes: dict[str, KgNode] = {}
        self.adjacency: dict[str, list[KgEdge]] = {}
        self.reverse: dict[str, list[KgEdge]] = {}
        self._confidence_floor = confidence_floor

    def add_node(self, node: KgNode) -> bool:
        """Add or merge a node; rejects low-confidence extractions (FR-12).

        Returns True when the node was written.
        """
        if node.confidence < self._confidence_floor:
            return False
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
            self.adjacency.setdefault(node.node_id, [])
            self.reverse.setdefault(node.node_id, [])
        else:
            self.nodes[node.node_id] = merge_nodes(existing, node)
        # T999: KG mutation → 001 audit stream (015 kg.mutated).
        _audit_kg_mutation(node)
        return True

    def add_edge(self, edge: KgEdge) -> bool:
        """Add an edge between two known nodes; rejects low-confidence edges."""
        if edge.confidence < self._confidence_floor:
            return False
        if edge.source not in self.nodes or edge.target not in self.nodes:
            return False
        self.adjacency.setdefault(edge.source, []).append(edge)
        self.reverse.setdefault(edge.target, []).append(edge)
        # T999: KG mutation (edge) → 001 audit stream (015 kg.mutated).
        _audit_kg_mutation(edge)
        return True

    def neighbours(self, node_id: str, *, relation: str | None = None) -> list[str]:
        """Outgoing neighbour ids, optionally filtered by relation type (FR-2)."""
        edges = self.adjacency.get(node_id, [])
        if relation:
            edges = [edge for edge in edges if edge.relation == relation]
        return [edge.target for edge in edges]

    def edges_of(self, node_id: str, *, relation: str | None = None) -> list[KgEdge]:
        edges = self.adjacency.get(node_id, [])
        if relation:
            edges = [edge for edge in edges if edge.relation == relation]
        return list(edges)

    def __len__(self) -> int:
        return len(self.nodes)
