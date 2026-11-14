"""Topological ordering with cycle detection (010 FR-3).

Cycle detection reports the cycle as a **node id sequence** (``A -> B -> C -> A``)
so the caller can point at the exact nodes involved (FR-3).
"""

from __future__ import annotations

from .graph import Graph


class CycleError(ValueError):
    """Raised when the graph contains a cycle; carries the cycle path."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = list(cycle)
        path = " -> ".join(cycle)
        super().__init__(f"cycle detected: {path}")


def _detect_cycle(graph: Graph) -> list[str] | None:
    """Return the first cycle found (as a node sequence), or ``None``."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node_id: WHITE for node_id in graph.nodes}
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        color[node_id] = GRAY
        stack.append(node_id)
        for neighbour in graph.adjacency.get(node_id, []):
            if color.get(neighbour) == GRAY:
                # Found a back-edge: the cycle is the tail of the stack from the
                # neighbour onward, closed by the neighbour itself.
                start = stack.index(neighbour)
                return stack[start:] + [neighbour]
            if color.get(neighbour) == WHITE:
                found = visit(neighbour)
                if found is not None:
                    return found
        stack.pop()
        color[node_id] = BLACK
        return None

    # Deterministic order for reproducible error messages.
    for node_id in sorted(graph.nodes):
        if color[node_id] == WHITE:
            found = visit(node_id)
            if found is not None:
                return found
    return None


def topological_order(graph: Graph) -> list[str]:
    """Kahn topological sort; raises ``CycleError`` when a cycle exists (FR-3).

    Ties are broken by node id so the order is deterministic (stable parallel
    scheduling).
    """
    cycle = _detect_cycle(graph)
    if cycle is not None:
        raise CycleError(cycle)

    indegree: dict[str, int] = {node_id: len(graph.dependencies(node_id)) for node_id in graph.nodes}
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []

    while ready:
        current = ready.pop(0)
        order.append(current)
        for neighbour in graph.adjacency.get(current, []):
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                ready.append(neighbour)
                ready.sort()

    if len(order) != len(graph.nodes):
        # Should be unreachable (cycle already checked) — keep a guard anyway.
        raise CycleError(_detect_cycle(graph) or [])
    return order
