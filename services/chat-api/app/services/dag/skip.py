"""Conditional skip (010 T013-T015) on the orchestration graph.

The DAG engine already records skips (FR-4), but this module exposes the
skip decision as an explicit, testable primitive: evaluate a node's condition
*at execution time* (T013: 编排执行到节点时求值), with three outcomes —
true → skip + optional downstream handling, false → run, syntax error →
fail-closed skip with the error recorded (US3 three Acceptances).

Skip traceability (T014): every skip carries ``reason`` = the evaluation
result + the marked downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.orchestration.conditions import ConditionError, evaluate_condition
from app.orchestration.graph import Graph, Node


class DownstreamPolicy:
    PROPAGATE = "propagate"   # transitively skip dependents
    CONTINUE = "continue"     # dependents still run
    NONE = "none"             # only the matched node is skipped


@dataclass
class SkipDecision:
    """The skip outcome for one node (010 T013-T015)."""
    node_id: str
    skipped: bool
    reason: str
    result: Any = None
    error: str | None = None
    affected_downstream: list[str] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "skipped": self.skipped,
            "reason": self.reason,
            "result": self.result,
            "error": self.error,
            "affected_downstream": list(self.affected_downstream),
        }


def evaluate_skip(
    graph: Graph,
    node_id: str,
    *,
    context: dict[str, Any] | None = None,
    downstream_policy: str = DownstreamPolicy.NONE,
) -> SkipDecision:
    """Evaluate a node's condition at execution time (010 T013-T015).

    - condition true  → skip (reason=condition_true); downstream handled per policy.
    - condition false → run  (reason=condition_false).
    - condition None  → run  (no condition = always run).
    - syntax error    → fail-closed skip (reason=syntax_error, error recorded,
      downstream untouched unless propagate is explicitly set) (US3 acceptance 3).
    """
    ctx = context or {}
    node = graph.nodes.get(node_id)
    if node is None:
        raise KeyError(f"unknown node: {node_id!r}")
    condition = node.condition

    if condition is None:
        return SkipDecision(node_id, skipped=False, reason="no_condition")

    try:
        result = bool(evaluate_condition(condition, ctx))
    except ConditionError as error:
        # US3 acceptance 3: a syntax error must not silently run — fail closed.
        return SkipDecision(
            node_id,
            skipped=True,
            reason="syntax_error",
            error=str(error),
        )

    if not result:
        return SkipDecision(node_id, skipped=False, reason="condition_false", result=result)

    affected: list[str] = []
    if downstream_policy == DownstreamPolicy.PROPAGATE:
        affected = sorted(graph.downstream_closure(node_id))
    return SkipDecision(
        node_id,
        skipped=True,
        reason="condition_true",
        result=result,
        affected_downstream=affected,
    )


def skip_trace_document(decision: SkipDecision) -> dict[str, Any]:
    """T014 — the skip traceability record (reason = evaluation + downstream)."""
    return decision.as_document()


__all__ = [
    "DownstreamPolicy",
    "SkipDecision",
    "evaluate_skip",
    "skip_trace_document",
]
