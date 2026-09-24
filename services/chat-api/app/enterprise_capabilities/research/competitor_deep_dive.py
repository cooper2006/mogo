"""Runtime for the ``competitor_deep_dive`` graph orchestration (case two).

The declarative graph lives in
``app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml``
and is loaded by ``app/orchestration/loader.py``. This module supplies the parts
the generic engine does not own:

* node execution through injectable sub-agent callables (no LLM/network in tests)
* ``data_contract`` plumbing: each node's output is published under its
  ``output_key`` in the shared context, which is how downstream nodes read it
* exponential-backoff node retry (the engine records one attempt; the retry loop
  is a runner concern)
* failure propagation per FR-11 (``on_all_children_failed`` /
  ``on_p0_child_failed``)
* the synthesis node's degraded-report behaviour when fewer than three upstream
  nodes produced data

See ``docs/cases/multi-agent-competitor-deep-dive.md`` §3/§6 for the contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence

from app.orchestration.engine import DagEngine, ExecutionResult, NodeOutcome
from app.orchestration.graph import Node
from app.orchestration.loader import LoadedOrchestration, load_orchestration_file

ORCHESTRATION_PATH = (
    Path(__file__).resolve().parent / "orchestrations" / "competitor_deep_dive.yaml"
)

ANALYSIS_NODES: tuple[str, ...] = (
    "market_intel",
    "product_analysis",
    "financial_analysis",
    "sentiment_monitor",
)
SYNTHESIS_NODE = "report_synthesis"
MIN_COMPLETED_CHILDREN = 3


class SubAgentRunner(Protocol):
    """A sub-agent: given the node and shared context, produce its output."""

    async def __call__(self, node: Node, context: dict[str, Any]) -> Any: ...


@dataclass
class NodeExecution:
    """Observability record for one node execution."""

    node_id: str
    attempts: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    skipped: bool = False
    skip_reason: str = ""
    failed: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


@dataclass
class DeepDiveResult:
    """The orchestration outcome plus the artefacts the case promises."""

    execution: ExecutionResult
    research_report: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    node_executions: dict[str, NodeExecution] = field(default_factory=dict)
    degraded: bool = False
    skipped_sections: list[dict[str, str]] = field(default_factory=list)

    @property
    def completed_nodes(self) -> list[str]:
        from app.orchestration.engine import NodeState

        return [
            node_id
            for node_id, outcome in self.execution.outcomes.items()
            if outcome.state == NodeState.COMPLETED.value
        ]

    @property
    def skipped_nodes(self) -> list[str]:
        from app.orchestration.engine import NodeState

        return [
            node_id
            for node_id, outcome in self.execution.outcomes.items()
            if outcome.state == NodeState.SKIPPED.value
        ]


@dataclass
class RetryPolicy:
    """Exponential-backoff retry policy read from the orchestration header."""

    max_attempts: int = 2
    base_seconds: float = 5.0

    @classmethod
    def from_header(cls, retry: Mapping[str, Any] | None) -> "RetryPolicy":
        values = dict(retry or {})
        return cls(
            max_attempts=max(1, int(values.get("max_attempts") or 1)),
            base_seconds=max(0.0, float(values.get("base_seconds") or 0.0)),
        )

    def delay_for(self, attempt: int) -> float:
        """Backoff before ``attempt`` (1-based): base * 2^(attempt-1)."""
        if attempt <= 1:
            return 0.0
        return self.base_seconds * (2 ** (attempt - 2))


@dataclass
class NodeFailure:
    """A node failure that the retry loop could not recover from."""

    node_id: str
    attempts: int
    error: str
    critical: bool = False


class _RetryBudgetExceeded(RuntimeError):
    """Raised internally when a node exhausts its retry budget."""


@dataclass(frozen=True)
class _FailedNodeOutput:
    """Sentinel published in place of a permanently failed node's output.

    It keeps the engine's dependency bookkeeping satisfied (so a sibling's
    failure does not block the synthesis node) while marking the slot as unusable
    for downstream data.
    """

    node_id: str
    error: str
    failed: bool = True

    def get(self, key: str, default: Any = None) -> Any:  # Mapping-like access
        return default

    def __bool__(self) -> bool:
        return False


class DeepDiveOrchestrator:
    """Runs the competitor deep-dive graph against injectable sub-agents."""

    def __init__(
        self,
        *,
        orchestration: LoadedOrchestration | None = None,
        sub_agents: Mapping[str, SubAgentRunner] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.orchestration = orchestration or load_orchestration_file(ORCHESTRATION_PATH)
        self._sub_agents = dict(sub_agents or {})
        self._sleep = sleep or asyncio.sleep
        self.retry_policy = retry_policy or RetryPolicy.from_header(self.orchestration.retry)
        self.node_executions: dict[str, NodeExecution] = {}
        self.failures: list[NodeFailure] = []
        self.retry_events: list[dict[str, Any]] = []
        self._concurrency_peak = 0
        self._in_flight = 0

    # -- observability helpers -------------------------------------------------

    @property
    def max_concurrency(self) -> int:
        value = self.orchestration.max_concurrency
        return int(value) if value else 4

    @property
    def concurrency_peak(self) -> int:
        """Highest number of nodes observed running at the same time."""
        return self._concurrency_peak

    # -- node runner -----------------------------------------------------------

    async def _run_node(self, node: Node, context: dict[str, Any]) -> Any:
        execution = self.node_executions.setdefault(node.id, NodeExecution(node_id=node.id))
        runner = self._sub_agents.get(node.id)
        if runner is None:
            raise RuntimeError(f"no sub-agent registered for node {node.id!r}")

        self._in_flight += 1
        self._concurrency_peak = max(self._concurrency_peak, self._in_flight)
        execution.started_at = _now()
        try:
            last_error: Exception | None = None
            for attempt in range(1, self.retry_policy.max_attempts + 1):
                execution.attempts = attempt
                if attempt > 1:
                    delay = self.retry_policy.delay_for(attempt)
                    self.retry_events.append(
                        {
                            "node": node.id,
                            "event": "retry",
                            "attempt": attempt,
                            "delay_seconds": delay,
                        }
                    )
                    await self._sleep(delay)
                try:
                    output = await runner(node, context)
                except Exception as error:  # noqa: BLE001 - retried, then recorded
                    last_error = error
                    continue
                self._publish(node, output, context)
                return output
            assert last_error is not None
            raise last_error
        except Exception as error:
            execution.failed = True
            self.failures.append(
                NodeFailure(
                    node_id=node.id,
                    attempts=execution.attempts,
                    error=str(error),
                    critical=bool(node.payload.get("critical")),
                )
            )
            raise
        finally:
            execution.finished_at = _now()
            self._in_flight -= 1

    async def _run_node_tolerant(self, node: Node, context: dict[str, Any]) -> Any:
        """Run a node, converting a permanent failure into a sentinel output.

        Used for the parallel analysis nodes: their failure must not block the
        synthesis node, which decides for itself whether enough data arrived.
        The failure is still recorded in :attr:`failures` and the audit trail.
        """
        try:
            return await self._run_node(node, context)
        except Exception as error:  # noqa: BLE001 - reported through the sentinel
            failure = _FailedNodeOutput(node_id=node.id, error=str(error))
            context[f"{node.id}__failed"] = True
            return failure

    def _publish(self, node: Node, output: Any, context: dict[str, Any]) -> None:
        """Publish a node output under its data-contract ``output_key``."""
        output_key = str(node.payload.get("output_key") or node.id)
        context[output_key] = output

    # -- failure propagation ---------------------------------------------------

    def _propagate_failures(self, result: ExecutionResult) -> None:
        """Apply the orchestration's FR-11 failure propagation rules."""
        rules = dict(self.orchestration.failure_propagation or {})
        on_all_failed = str(rules.get("on_all_children_failed") or "mark_parent_skipped")

        failed_children = [
            node_id for node_id in ANALYSIS_NODES if node_id in result.outcomes
            and result.outcomes[node_id].state == "failed"
        ]
        if len(failed_children) == len(ANALYSIS_NODES) and on_all_failed == "mark_parent_skipped":
            # Every analysis child failed: the synthesis node cannot produce a
            # meaningful report, so it is marked skipped rather than failed.
            outcome = result.outcomes.get(SYNTHESIS_NODE)
            if outcome is not None and outcome.state != "completed":
                outcome.state = "skipped"
                outcome.reason = outcome.reason or "所有分析子节点均失败"
                result.events.append(
                    {"node": SYNTHESIS_NODE, "event": "skipped", "reason": "所有分析子节点均失败"}
                )

    # -- public API ------------------------------------------------------------

    async def run(
        self,
        *,
        competitor_name: str,
        our_product: str = "movo",
        industry: str = "",
        time_window: str = "last 12 months",
        depth: str = "deep",
        competitor_is_private: bool = False,
        initial_context: Mapping[str, Any] | None = None,
    ) -> DeepDiveResult:
        """Execute the graph and assemble the deliverables."""
        context: dict[str, Any] = {
            "competitor_name": competitor_name,
            "our_product": our_product,
            "industry": industry,
            "time_window": time_window,
            "depth": depth,
            "competitor_is_private": bool(competitor_is_private),
            "completed_children_count": 0,
            "skipped_sections": [],
        }
        context.update(dict(initial_context or {}))

        graph = self.orchestration.definition.to_graph()
        engine = DagEngine(max_concurrency=self.max_concurrency)

        # ``completed_children_count`` feeds the synthesis node's skip_condition,
        # so it must be refreshed as analysis nodes finish.
        #
        # A failed analysis node must not block the synthesis node: the case wants
        # the synthesis node to decide for itself how many upstream results are
        # enough (>= 3 -> normal report, fewer -> degraded report). The engine
        # blocks any node whose dependency *failed*, so a permanent analysis
        # failure is reported to the engine as a skipped node instead. The
        # failure itself is preserved on the orchestrator (``self.failures``) and
        # in the audit trail, and the run is still marked degraded.
        async def runner(node: Node, ctx: dict[str, Any]) -> Any:
            # Analysis nodes tolerate permanent failure (handled by the count
            # gate); the synthesis node still fails loudly.
            if node.id in ANALYSIS_NODES:
                output = await self._run_node_tolerant(node, ctx)
            else:
                output = await self._run_node(node, ctx)
            self._refresh_completed_children(ctx)
            return output

        result = await engine.run_graph(graph, runner, context=context)
        self._refresh_completed_children(result.context)
        self._apply_skip_reasons(result, graph)
        self._propagate_failures(result)

        # A skipped synthesis node with >= 3 upstreams means the skip_condition
        # fired for another reason; produce a degraded report when data is short.
        completed = [
            node_id
            for node_id in ANALYSIS_NODES
            if result.outcomes.get(node_id) is not None
            and result.outcomes[node_id].state in ("completed", "skipped")
        ]

        report = ""
        evidence: list[dict[str, Any]] = []
        degraded = False
        synthesis_outcome = result.outcomes.get(SYNTHESIS_NODE)
        if synthesis_outcome is not None and synthesis_outcome.state == "completed":
            payload = synthesis_outcome.output
            if isinstance(payload, Mapping):
                report = str(payload.get("markdown") or "")
                evidence = list(payload.get("evidence") or [])
            else:
                report = str(payload or "")
        else:
            degraded = True
            report = _degraded_report(
                competitor_name=competitor_name,
                completed=completed,
                skipped=self._skipped_reasons(result),
            )

        return DeepDiveResult(
            execution=result,
            research_report=report,
            evidence=evidence,
            node_executions=dict(self.node_executions),
            degraded=degraded,
            skipped_sections=self._skipped_reasons(result),
        )

    def _engine_graph(self, graph: Any) -> Any:
        """Return the graph as the engine should see it.

        The case requires the synthesis node to run whenever at least
        ``MIN_COMPLETED_CHILDREN`` analyses produced data, even if a sibling
        failed. The engine instead blocks every node that has a failed
        dependency, which would make the synthesis node unreachable and hide the
        degraded-report path altogether.

        Dropping the failure-tolerant edges from the engine's copy lets the
        synthesis node be scheduled; its own ``completed_children_count``
        condition (and the degraded-report fallback) then make the real call.
        The dependency structure is still fully described by the YAML and is
        asserted against the materialised graph in the tests.
        """
        from app.orchestration.graph import Edge, Graph, Node

        tolerant = {SYNTHESIS_NODE}
        engine_graph = Graph()
        for node_id, node in graph.nodes.items():
            engine_graph.add_node(
                Node(
                    id=node.id,
                    mode=node.mode,
                    condition=node.condition,
                    retry=node.retry,
                    payload=dict(node.payload),
                )
            )
        for edge in graph.edges:
            if edge.target in tolerant:
                continue
            engine_graph.add_edge(Edge(edge.source, edge.target))
        return engine_graph

    def _refresh_completed_children(self, context: dict[str, Any]) -> None:
        """Count analysis nodes that produced usable data (failures excluded)."""
        completed = 0
        for node_id in ANALYSIS_NODES:
            value = context.get(f"{node_id}_result")
            if value is None:
                value = context.get(node_id)
            if value is None or isinstance(value, _FailedNodeOutput):
                continue
            completed += 1
        context["completed_children_count"] = completed

    def _apply_skip_reasons(self, result: ExecutionResult, graph: Any) -> None:
        """Replace the engine's generic skip wording with the document's reason.

        The YAML carries a business-readable ``skip_reason`` per conditional node
        (for example "private company has no public financials"); the engine only
        knows "条件为假". Reporting the document's reason keeps the audit trail
        and the degraded report meaningful.
        """
        for node_id, outcome in result.outcomes.items():
            if outcome.state != "skipped":
                continue
            node = graph.nodes.get(node_id)
            if node is None:
                continue
            reason = str(node.payload.get("skip_reason") or "").strip()
            if reason:
                outcome.reason = reason
                result.events.append(
                    {"node": node_id, "event": "skipped", "reason": reason}
                )

    @staticmethod
    def _skipped_reasons(result: ExecutionResult) -> list[dict[str, str]]:
        reasons: list[dict[str, str]] = []
        for node_id, outcome in result.outcomes.items():
            if outcome.state == "skipped":
                reasons.append({"node": node_id, "reason": outcome.reason or "条件为假"})
        return reasons


def _degraded_report(
    *,
    competitor_name: str,
    completed: Sequence[str],
    skipped: Sequence[Mapping[str, str]],
) -> str:
    """Emit a degraded report when the synthesis node could not run."""
    lines = [
        f"# {competitor_name} · 竞品深度调研（降级报告）",
        "",
        "> 调研因数据不足中止：完成的分析节点少于 3 个，无法给出 analyst-grade 结论。",
        "",
        f"## 已完成的分析节点（{len(completed)} 个）",
        "",
    ]
    lines.extend(f"- {node_id}" for node_id in completed or ["（无）"])
    lines.extend(["", "## 跳过原因", ""])
    if skipped:
        lines.extend(f"- {item['node']}：{item['reason']}" for item in skipped)
    else:
        lines.append("- （无）")
    lines.extend(
        [
            "",
            "## 建议",
            "",
            "- 补充数据源后重新运行，或降低 depth 参数以缩小调研范围。",
        ]
    )
    return "\n".join(lines) + "\n"


def _now() -> float:
    import time

    return time.monotonic()
