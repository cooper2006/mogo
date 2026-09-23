"""Supervisor orchestration mode (010 FR-1 / FR-11).

A supervisor node dispatches work to child nodes, aggregates their results, and
propagates failure:

* **supervisor itself fails** -> the whole orchestration fails;
* **all children fail** -> the supervisor fails;
* a configurable threshold lets "too many children failed" also fail the
  supervisor (FR-11).

The mode is transport-agnostic: children run through the same async runner the
graph engine uses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .graph import Node

# Default: the supervisor fails once this fraction of children fail.
DEFAULT_CHILD_FAILURE_THRESHOLD = 1.0   # all children must fail

ChildRunner = Callable[[Node, dict[str, Any]], Awaitable[Any]]


@dataclass
class ChildOutcome:
    """The outcome of one child dispatch."""

    node_id: str
    ok: bool
    output: Any = None
    error: str = ""


@dataclass
class SupervisorResult:
    """Aggregated result of a supervisor run."""

    supervisor_id: str
    children: list[ChildOutcome] = field(default_factory=list)
    supervisor_failed: bool = False
    reason: str = ""
    aggregated: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.supervisor_failed

    @property
    def failed_children(self) -> list[str]:
        return [child.node_id for child in self.children if not child.ok]

    @property
    def successful_children(self) -> list[str]:
        return [child.node_id for child in self.children if child.ok]


class Supervisor:
    """Dispatches children, aggregates results, and propagates failure."""

    def __init__(
        self,
        supervisor_id: str,
        children: list[Node],
        *,
        child_failure_threshold: float = DEFAULT_CHILD_FAILURE_THRESHOLD,
        max_concurrency: int = 4,
    ) -> None:
        self.supervisor_id = supervisor_id
        self.children = list(children)
        self.threshold = float(child_failure_threshold)
        self.max_concurrency = max(1, int(max_concurrency))

    async def run(
        self,
        runner: ChildRunner,
        *,
        context: dict[str, Any] | None = None,
        supervisor_ok: bool = True,
        supervisor_error: str = "",
    ) -> SupervisorResult:
        """Dispatch every child and aggregate.

        ``supervisor_ok=False`` simulates the supervisor itself failing, which
        fails the whole run regardless of the children (FR-11).
        """
        if not supervisor_ok:
            return SupervisorResult(
                supervisor_id=self.supervisor_id,
                supervisor_failed=True,
                reason=f"监督节点失败：{supervisor_error}" if supervisor_error else "监督节点失败",
            )

        shared = dict(context or {})
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def dispatch(child: Node) -> ChildOutcome:
            async with semaphore:
                try:
                    output = await runner(child, shared)
                except Exception as error:  # noqa: BLE001 - surfaced as a child failure
                    return ChildOutcome(node_id=child.id, ok=False, error=str(error))
                shared[child.id] = output
                return ChildOutcome(node_id=child.id, ok=True, output=output)

        outcomes = await asyncio.gather(*(dispatch(child) for child in self.children))
        children = list(outcomes)
        failed = [child for child in children if not child.ok]

        if not children:
            # No children at all: the supervisor has nothing to aggregate.
            return SupervisorResult(
                supervisor_id=self.supervisor_id,
                supervisor_failed=True,
                reason="监督节点无子节点",
            )

        failure_ratio = len(failed) / len(children)
        supervisor_failed = failure_ratio >= self.threshold
        reason = ""
        if supervisor_failed:
            reason = (
                f"子节点失败率 {failure_ratio:.0%} 达到阈值 {self.threshold:.0%}"
                if self.threshold < 1.0
                else "全部子节点失败"
            )

        aggregated = {
            "children": {child.node_id: child.output for child in children if child.ok},
            "failed": [child.node_id for child in children if not child.ok],
            "successCount": len(children) - len(failed),
            "failureCount": len(failed),
        }
        return SupervisorResult(
            supervisor_id=self.supervisor_id,
            children=children,
            supervisor_failed=supervisor_failed,
            reason=reason,
            aggregated=aggregated,
        )


async def run_hybrid(
    *,
    sequential_ids: list[str],
    parallel_ids: list[str],
    runner: Callable[[str, dict[str, Any]], Awaitable[Any]],
    context: dict[str, Any] | None = None,
    max_concurrency: int = 4,
) -> dict[str, Any]:
    """Hybrid mode: run a sequential prefix, then fan out the parallel stage.

    Results from the sequential stage are available to the parallel stage via the
    shared context.
    """
    shared = dict(context or {})
    order: list[str] = []
    for node_id in sequential_ids:
        shared[node_id] = await runner(node_id, shared)
        order.append(node_id)

    semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def run_parallel(node_id: str) -> tuple[str, Any]:
        async with semaphore:
            return node_id, await runner(node_id, shared)

    if parallel_ids:
        results = await asyncio.gather(*(run_parallel(node_id) for node_id in parallel_ids))
        for node_id, output in results:
            shared[node_id] = output
            order.append(node_id)

    return {"order": order, "context": shared}
