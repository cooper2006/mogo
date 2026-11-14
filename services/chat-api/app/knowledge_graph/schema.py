"""Knowledge-graph schema: node/edge models and the generic type set (015 FR-1/FR-7).

Entity types: person / organization / product / event.
Relation types: membership / responsible / reference / association.
The schema is extensible per domain (clarify OQ-2); the types below are the
enterprise-generic defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ENTITY_TYPES: tuple[str, ...] = ("person", "organization", "product", "event")
RELATION_TYPES: tuple[str, ...] = ("membership", "responsible", "reference", "association")

DEFAULT_MAX_HOPS = 3

# Extraction below this confidence is not written into the graph (FR-12).
DEFAULT_CONFIDENCE_FLOOR = 0.5


class KgError(ValueError):
    """Raised for an invalid node/edge definition."""


@dataclass
class KgNode:
    """An entity node."""

    node_id: str
    entity_type: str = "person"
    name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    source_ref: str = ""            # 014 biz_entities pointer (FR-13)
    confidence: float = 1.0
    conflicted: bool = False        # set when merged attributes disagree (FR-3)

    def __post_init__(self) -> None:
        if not str(self.node_id or "").strip():
            raise KgError("node_id must not be empty")
        if self.entity_type not in ENTITY_TYPES:
            raise KgError(f"unknown entity type: {self.entity_type!r}")


@dataclass
class KgEdge:
    """A directed relation between two nodes."""

    source: str
    target: str
    relation: str = "association"
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not str(self.source or "").strip() or not str(self.target or "").strip():
            raise KgError("edge endpoints must not be empty")
        if self.source == self.target:
            raise KgError("self-relation is not allowed")
        if self.relation not in RELATION_TYPES:
            raise KgError(f"unknown relation type: {self.relation!r}")
