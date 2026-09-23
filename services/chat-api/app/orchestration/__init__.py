"""DAG orchestration engine (feature 010).

A general-purpose DAG engine with four modes (sequential / supervisor / hybrid /
graph), topological ordering with cycle detection, conditional skipping via a
**restricted JSON condition object** (no arbitrary code), and node-level
exponential-backoff retry.

This package holds the dependency-light core (graph / topo / conditions), so it is
unit-testable without the DSH runtime or a database.
"""

from __future__ import annotations

from .conditions import ConditionError, evaluate_condition
from .engine import (
    DEFAULT_MAX_CONCURRENCY,
    DagEngine,
    ExecutionResult,
    NodeOutcome,
    NodeState,
)
from .graph import Edge, Graph, GraphError, Node
from .topo import CycleError, topological_order

__all__ = [
    "Node",
    "Edge",
    "Graph",
    "GraphError",
    "topological_order",
    "CycleError",
    "evaluate_condition",
    "ConditionError",
    "DagEngine",
    "ExecutionResult",
    "NodeOutcome",
    "NodeState",
    "DEFAULT_MAX_CONCURRENCY",
]
