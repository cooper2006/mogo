"""Multi-hop traversal with cycle protection (015 FR-2 / FR-4 / FR-5 / FR-11).

Traversal is bounded by a hop limit (default 3, clarify OQ-3) and never revisits a
node (cycle guard, FR-11). When a hop cannot be resolved the path is reported as
**broken at that hop** rather than guessed (FR-5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import DEFAULT_MAX_HOPS
from .store import KgStore


@dataclass
class CycleGuard:
    """Tracks visited nodes to prevent revisiting (A -> B -> A)."""

    visited: set[str] = field(default_factory=set)

    def visit(self, node_id: str) -> bool:
        """Mark ``node_id`` visited; returns False when it was already seen."""
        if node_id in self.visited:
            return False
        self.visited.add(node_id)
        return True


@dataclass
class MultiHopResult:
    """Outcome of a multi-hop traversal."""

    paths: list[list[str]] = field(default_factory=list)
    hops: int = 0
    broken_at: int | None = None       # hop index where the path broke, if any
    truncated: bool = False            # True when the hop limit cut the search

    @property
    def broken(self) -> bool:
        return self.broken_at is not None

    def describe_break(self, missing_relation: str = "") -> str:
        """Human-readable break description (FR-5)."""
        if self.broken_at is None:
            return ""
        suffix = f"（缺失关系：{missing_relation}）" if missing_relation else ""
        return f"路径在第 {self.broken_at} 跳断裂{suffix}"


def traverse(
    store: KgStore,
    start: str,
    *,
    max_hops: int = DEFAULT_MAX_HOPS,
    relation: str | None = None,
) -> MultiHopResult:
    """Traverse up to ``max_hops`` from ``start``, returning all simple paths.

    Cycles are cut by the guard; exceeding the hop limit marks the result
    ``truncated`` rather than looping.
    """
    if start not in store.nodes:
        return MultiHopResult(broken_at=1)

    result = MultiHopResult()
    guard = CycleGuard()
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    guard.visit(start)

    while stack:
        current, path = stack.pop()
        depth = len(path) - 1
        if depth >= max_hops:
            result.truncated = True
            result.paths.append(path)
            continue
        neighbours = store.neighbours(current, relation=relation)
        if not neighbours:
            if depth > 0:
                result.paths.append(path)
            else:
                # No outgoing edges at the start node: the path is broken at hop 1.
                result.broken_at = 1
            continue
        for neighbour in neighbours:
            if not guard.visit(neighbour):
                # Cycle: record the path but do not extend it (FR-11).
                result.paths.append(path + [neighbour])
                continue
            stack.append((neighbour, path + [neighbour]))

    result.hops = max((len(path) - 1 for path in result.paths), default=0)
    return result
