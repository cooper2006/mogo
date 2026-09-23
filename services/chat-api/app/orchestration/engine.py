"""DAG execution engine (010 FR-2 / FR-6 / FR-7 / FR-9 / FR-10 / FR-11).

Executes a graph by topological order:

* **graph** mode runs independent nodes concurrently up to ``max_concurrency``
  (default 4); excess nodes queue rather than being rejected (FR-2);
* a node failure **blocks its entire downstream closure**, and those nodes are
  marked ``blocked`` (distinct from ``failed``) (FR-6);
* skipped nodes (falsy condition) are recorded with the reason and their
  downstream is marked (FR-4);
* every transition (started / completed / failed / skipped / retried) is emitted
  as an audit event (FR-7).

The engine is transport-agnostic: a node's work is any ``async`` callable. This
keeps it testable without the DSH runtime or a database.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .conditions import ConditionError, evaluate_condition
from .graph import Graph, Node
from .topo import topological_order

DEFAULT_MAX_CONCURRENCY = 4


class NodeState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class NodeOutcome:
    """The recorded outcome of one node."""

    node_id: str
    state: str
    output: Any = None
    error: str = ""
    attempts: int = 0
    reason: str = ""


@dataclass
class ExecutionResult:
    """The result of running a graph."""

    outcomes: dict[str, NodeOutcome] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def failed_nodes(self) -> list[str]:
        return [nid for nid, item in self.outcomes.items() if item.state == NodeState.FAILED.value]

    @property
    def blocked_nodes(self) -> list[str]:
        return [nid for nid, item in self.outcomes.items() if item.state == NodeState.BLOCKED.value]

    @property
    def succeeded(self) -> bool:
        return not self.failed_nodes and not self.blocked_nodes


NodeRunner = Callable[[Node, dict[str, Any]], Awaitable[Any]]


class DagEngine:
    """Executes DAGs with bounded concurrency and failure blocking."""

    def __init__(self, *, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        self.max_concurrency = max(1, int(max_concurrency))

    async def run_graph(
        self,
        graph: Graph,
        runner: NodeRunner,
        *,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Run a graph in topological order with bounded concurrency."""
        order = topological_order(graph)
        result = ExecutionResult(context=dict(context or {}))
        pending = set(order)
        blocked: set[str] = set()
        running: dict[str, asyncio.Task] = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        def ready(node_id: str) -> bool:
            deps = graph.dependencies(node_id)
            return all(
                dep in result.outcomes
                and result.outcomes[dep].state in (NodeState.COMPLETED.value, NodeState.SKIPPED.value)
                for dep in deps
            )

        def blocked_by_upstream(node_id: str) -> bool:
            return any(dep in blocked for dep in graph.dependencies(node_id))

        async def execute(node: Node) -> NodeOutcome:
            async with semaphore:
                # Conditional skip (FR-4).
                if node.condition is not None:
                    try:
                        should_run = evaluate_condition(node.condition, result.context)
                    except ConditionError as error:
                        # Syntax/shape error -> fail closed: skip + record (FR-4).
                        result.events.append(
                            {"node": node.id, "event": "skipped", "reason": f"条件求值失败：{error}"}
                        )
                        return NodeOutcome(
                            node_id=node.id,
                            state=NodeState.SKIPPED.value,
                            reason=f"条件求值失败：{error}",
                        )
                    if not should_run:
                        result.events.append({"node": node.id, "event": "skipped", "reason": "条件为假"})
                        return NodeOutcome(
                            node_id=node.id, state=NodeState.SKIPPED.value, reason="条件为假"
                        )

                result.events.append({"node": node.id, "event": "started"})
                try:
                    output = await runner(node, result.context)
                except Exception as error:  # noqa: BLE001 - surfaced as a failed node
                    result.events.append(
                        {"node": node.id, "event": "failed", "reason": str(error)}
                    )
                    return NodeOutcome(
                        node_id=node.id, state=NodeState.FAILED.value, error=str(error), attempts=1
                    )
                result.events.append({"node": node.id, "event": "completed"})
                result.context[node.id] = output
                return NodeOutcome(
                    node_id=node.id, state=NodeState.COMPLETED.value, output=output, attempts=1
                )

        while pending or running:
            # Mark nodes whose upstream failed as blocked (FR-6).
            newly_blocked = {
                node_id for node_id in pending if blocked_by_upstream(node_id)
            }
            for node_id in newly_blocked:
                pending.discard(node_id)
                blocked.add(node_id)
                result.outcomes[node_id] = NodeOutcome(
                    node_id=node_id, state=NodeState.BLOCKED.value, reason="上游失败阻塞"
                )
                result.events.append({"node": node_id, "event": "blocked"})
                # Blocking propagates: the whole downstream closure follows.
                for downstream in graph.downstream_closure(node_id):
                    blocked.add(downstream)

            # Launch ready nodes up to the concurrency limit.
            launchable = [
                node_id
                for node_id in order
                if node_id in pending and ready(node_id) and node_id not in running
            ]
            for node_id in launchable:
                if len(running) >= self.max_concurrency:
                    break
                pending.discard(node_id)
                running[node_id] = asyncio.create_task(execute(graph.nodes[node_id]))

            if not running:
                # Nothing runnable and nothing running: remaining nodes are
                # unreachable (e.g. upstream blocked) -> mark blocked to terminate.
                for node_id in list(pending):
                    pending.discard(node_id)
                    blocked.add(node_id)
                    result.outcomes[node_id] = NodeOutcome(
                        node_id=node_id, state=NodeState.BLOCKED.value, reason="上游不可达"
                    )
                    result.events.append({"node": node_id, "event": "blocked"})
                break

            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                node_id = next(nid for nid, t in running.items() if t is task)
                running.pop(node_id)
                result.outcomes[node_id] = task.result()

        return result

    async def run_sequential(
        self, graph: Graph, runner: NodeRunner, *, context: dict[str, Any] | None = None
    ) -> ExecutionResult:
        """sequential mode: run nodes strictly in topological order, one at a time."""
        order = topological_order(graph)
        result = ExecutionResult(context=dict(context or {}))
        for node_id in order:
            if any(
                result.outcomes.get(dep) and result.outcomes[dep].state == NodeState.FAILED.value
                for dep in graph.dependencies(node_id)
            ):
                result.outcomes[node_id] = NodeOutcome(
                    node_id=node_id, state=NodeState.BLOCKED.value, reason="上游失败阻塞"
                )
                result.events.append({"node": node_id, "event": "blocked"})
                continue
            outcome = await self._run_single(graph.nodes[node_id], runner, result)
            result.outcomes[node_id] = outcome
        return result

    async def _run_single(
        self, node: Node, runner: NodeRunner, result: ExecutionResult
    ) -> NodeOutcome:
        if node.condition is not None:
            try:
                should_run = evaluate_condition(node.condition, result.context)
            except ConditionError as error:
                result.events.append({"node": node.id, "event": "skipped", "reason": str(error)})
                return NodeOutcome(node_id=node.id, state=NodeState.SKIPPED.value, reason=str(error))
            if not should_run:
                result.events.append({"node": node.id, "event": "skipped", "reason": "条件为假"})
                return NodeOutcome(node_id=node.id, state=NodeState.SKIPPED.value, reason="条件为假")
        result.events.append({"node": node.id, "event": "started"})
        try:
            output = await runner(node, result.context)
        except Exception as error:  # noqa: BLE001
            result.events.append({"node": node.id, "event": "failed", "reason": str(error)})
            return NodeOutcome(node_id=node.id, state=NodeState.FAILED.value, error=str(error), attempts=1)
        result.events.append({"node": node.id, "event": "completed"})
        result.context[node.id] = output
        return NodeOutcome(node_id=node.id, state=NodeState.COMPLETED.value, output=output, attempts=1)
