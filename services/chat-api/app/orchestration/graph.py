"""DAG node/edge model (010 FR-1 / FR-2).

A graph carries nodes (with optional skip conditions and per-node retry config)
and directed edges. Node data flows through a shared context: an upstream node's
output is written under its id, and downstream nodes read by key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

VALID_MODES = ("sequential", "supervisor", "hybrid", "graph")


class GraphError(ValueError):
    """Raised for an invalid graph definition."""


@dataclass
class Node:
    """A unit of work in the graph."""

    id: str
    mode: str = "graph"
    condition: dict[str, Any] | None = None     # restricted JSON condition object
    retry: dict[str, Any] | None = None          # {"max_attempts": n, "base_seconds": s}
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.id or "").strip():
            raise GraphError("node id must not be empty")


@dataclass
class Edge:
    """A directed dependency ``source -> target``."""

    source: str
    target: str


class Graph:
    """A directed acyclic graph of nodes and edges."""

    def __init__(self, nodes: Iterable[Node] | None = None, edges: Iterable[Edge] | None = None) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.adjacency: dict[str, list[str]] = {}
        self.reverse: dict[str, list[str]] = {}
        for node in nodes or []:
            self.add_node(node)
        for edge in edges or []:
            self.add_edge(edge)

    def add_node(self, node: Node) -> None:
        if node.id in self.nodes:
            raise GraphError(f"duplicate node id: {node.id}")
        self.nodes[node.id] = node
        self.adjacency.setdefault(node.id, [])
        self.reverse.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self.nodes:
            raise GraphError(f"edge source not found: {edge.source}")
        if edge.target not in self.nodes:
            raise GraphError(f"edge target not found: {edge.target}")
        if edge.source == edge.target:
            raise GraphError(f"self-loop not allowed: {edge.source}")
        self.edges.append(edge)
        self.adjacency.setdefault(edge.source, []).append(edge.target)
        self.reverse.setdefault(edge.target, []).append(edge.source)

    def dependencies(self, node_id: str) -> list[str]:
        return list(self.reverse.get(node_id, []))

    def dependents(self, node_id: str) -> list[str]:
        return list(self.adjacency.get(node_id, []))

    def downstream_closure(self, node_id: str) -> set[str]:
        """All transitive dependents of ``node_id`` (used for failure blocking).

        A node failure blocks its *entire* downstream closure, not just the direct
        dependents (FR-6).
        """
        seen: set[str] = set()
        stack = list(self.adjacency.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.adjacency.get(current, []))
        return seen

    def roots(self) -> list[str]:
        return [node_id for node_id in self.nodes if not self.reverse.get(node_id)]

    def __len__(self) -> int:
        return len(self.nodes)
