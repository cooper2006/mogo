"""Knowledge graph layer (feature 015).

Extracts entities/relations, stores them as a MongoDB adjacency structure (first
delivery; migrate to Neo4j past the clarify threshold), and answers multi-hop
queries with cycle protection. Runs alongside 005 RAG.

This package holds the dependency-light core (schema / store / query), so it is
unit-testable without a database.
"""

from __future__ import annotations

from .schema import (
    DEFAULT_MAX_HOPS,
    ENTITY_TYPES,
    RELATION_TYPES,
    KgEdge,
    KgNode,
)
from .consistency import (
    CardinalityRule,
    Conflict,
    ConstraintBundle,
    MutualExclusion,
    check_all,
    mark_conflicts,
)
from .store import KgStore, merge_nodes
from .query import CycleGuard, MultiHopResult, traverse

__all__ = [
    "KgNode",
    "KgEdge",
    "ENTITY_TYPES",
    "RELATION_TYPES",
    "DEFAULT_MAX_HOPS",
    "KgStore",
    "merge_nodes",
    "traverse",
    "MultiHopResult",
    "CycleGuard",
    "Conflict",
    "ConstraintBundle",
    "MutualExclusion",
    "CardinalityRule",
    "check_all",
    "mark_conflicts",
]
