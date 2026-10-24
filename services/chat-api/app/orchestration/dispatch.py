"""Unified mode dispatch (044 FR-001 / FR-012).

``execute_orchestration`` turns a ``LoadedOrchestration`` into a run by selecting
the executor for its document-level ``mode``. The four 010 modes keep their exact
execution path and semantics (FR-010, hard constraint): ``graph`` and
``sequential`` are delegated to :mod:`app.orchestration.engine`, ``supervisor``
and ``hybrid`` are delegated to :mod:`app.orchestration.supervisor` (callers
supply the grouping explicitly, since those modes currently have no production
call site — 044 R-13 records this).

The two new modes are executed here:

* ``round_robin`` (document level) treats **every graph node as a candidate** of a
  single logical task; candidates run concurrently under the document
  ``max_concurrency`` and one output is selected (044 FR-002/FR-003).
* ``debate`` (document level) resolves the graph into ``pro`` / ``con`` / optional
  ``arbiter`` role nodes and runs the alternating protocol
  (044 FR-005/FR-006/FR-007).

Node-level dispatch is available through :func:`wrap_node_runner`, so a
``round_robin`` / ``debate`` node can also appear as a child of a ``graph``
execution and behave as one atomic success-or-failure (FR-009 / R-16).

Unknown modes fail closed with ``OrchestrationLoadError`` (R-11): an undeclared
mode still defaults to ``graph`` at load time (``loader.py``), but a declared mode
that is not one of the six is never silently downgraded here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from .debate import ARBITER_ABSENT, DebateError, DebateResult, run_debate
from .engine import DagEngine, DEFAULT_MAX_CONCURRENCY, ExecutionResult, NodeRunner
from .graph import Graph, Node
from .loader import OrchestrationLoadError
from .loader import LoadedOrchestration
from .round_robin import (
    CandidateOutcome,
    CandidateRunner,
    CandidateSpec,
    DEFAULT_MAX_CONCURRENCY as RR_DEFAULT_MAX_CONCURRENCY,
    DEFAULT_STRATEGY,
    RoundRobinError,
    SelectionResult,
    balanced_take,
    candidate_node,
    parse_instances,
    run_round_robin,
    score_of,
    select_candidate,
)
from .supervisor import Supervisor, run_hybrid

MODE_ROUND_ROBIN = "round_robin"
MODE_DEBATE = "debate"
NEW_MODES = (MODE_ROUND_ROBIN, MODE_DEBATE)

ROLE_PRO = "pro"
ROLE_CON = "con"
ROLE_ARBITER = "arbiter"


async def execute_orchestration(
    loaded: LoadedOrchestration,
    runner: Callable[[Node, dict[str, Any]], Awaitable[Any]],
    *,
    context: dict[str, Any] | None = None,
    engine: DagEngine | None = None,
    sequential_ids: list[str] | None = None,
    parallel_ids: list[str] | None = None,
    supervisor_id: str | None = None,
) -> ExecutionResult | SelectionResult | DebateResult:
    """Run a loaded orchestration according to its document-level ``mode``.

    ``graph`` / ``sequential`` keep their existing behaviour bit-for-bit
    (FR-010); passing an ``engine`` reuses a caller-provided engine exactly as
    the 010 call sites do. ``supervisor`` and ``hybrid`` require the caller to
    name the grouping (see :mod:`app.orchestration.supervisor`).
    """
    if loaded is None:
        raise OrchestrationLoadError("未提供编排定义")
    mode = loaded.mode
    ctx = dict(context or {})
    graph = loaded.definition.to_graph()

    if mode == "graph":
        if engine is None:
            engine = DagEngine(max_concurrency=loaded.max_concurrency or DEFAULT_MAX_CONCURRENCY)
        return await engine.run_graph(graph, runner, context=ctx)

    if mode == "sequential":
        if engine is None:
            engine = DagEngine(max_concurrency=loaded.max_concurrency or DEFAULT_MAX_CONCURRENCY)
        return await engine.run_sequential(graph, runner, context=ctx)

    if mode == "supervisor":
        if supervisor_id is None and graph.nodes:
            supervisor_id = next(iter(graph.nodes))
        children = [node for node_id, node in graph.nodes.items() if node_id != supervisor_id]
        supervisor = Supervisor(
            supervisor_id or "__supervisor__",
            children,
            child_failure_threshold=float(_header_value(loaded, "child_failure_threshold") or 1.0),
            max_concurrency=loaded.max_concurrency or DEFAULT_MAX_CONCURRENCY,
        )
        return await supervisor.run(
            runner=lambda node_id: runner(graph.nodes[node_id], ctx) if node_id in graph.nodes else runner(Node(id=node_id), ctx),
            context=ctx,
        )

    if mode == "hybrid":
        return await run_hybrid(
            sequential_ids=sequential_ids or [],
            parallel_ids=parallel_ids or [],
            runner=lambda node_id: runner(graph.nodes[node_id], ctx),
            context=ctx,
            max_concurrency=loaded.max_concurrency or DEFAULT_MAX_CONCURRENCY,
        )

    if mode == MODE_ROUND_ROBIN:
        return await _run_round_robin_document(loaded, runner, context=ctx)

    if mode == MODE_DEBATE:
        return await _run_debate_document(loaded, runner, context=ctx)

    raise OrchestrationLoadError(f"未知编排模式：{mode!r}（允许 {', '.join(_all_modes())}）")


def _header_value(loaded: LoadedOrchestration, key: str, default: Any = None) -> Any:
    """Read a document-level knob from the raw YAML (``orchestration:`` block first)."""
    header = (loaded.raw or {}).get("orchestration")
    if isinstance(header, Mapping):
        return header.get(key, default)
    return (loaded.raw or {}).get(key, default)


def _all_modes() -> tuple[str, ...]:
    from .graph import VALID_MODES  # local import to avoid a cycle at import time

    return VALID_MODES


async def _run_round_robin_document(
    loaded: LoadedOrchestration,
    runner: Callable[[Node, dict[str, Any]], Awaitable[Any]],
    *,
    context: dict[str, Any],
) -> tuple[SelectionResult, dict[str, Any]]:
    """Document-level round_robin: every graph node is a candidate of one task."""
    graph = loaded.definition.to_graph()
    nodes = list(graph.nodes.values())
    if not nodes:
        raise RoundRobinError("round_robin 模式需要至少一个候选节点")

    semaphore = asyncio.Semaphore(max(1, int(loaded.max_concurrency or RR_DEFAULT_MAX_CONCURRENCY)))
    outcomes: list[CandidateOutcome] = [
        CandidateOutcome(label=node.id, status="completed", order=index) for index, node in enumerate(nodes)
    ]

    async def execute(index: int, node: Node) -> None:
        outcome = outcomes[index]
        async with semaphore:
            try:
                output = await runner(node, dict(context))
            except Exception as error:  # noqa: BLE001 - recorded below
                outcome.status = "failed"
                outcome.error = f"{type(error).__name__}: {error}"
                return
        outcome.output = output
        outcome.score = score_of(output)

    await asyncio.gather(*(execute(index, node) for index, node in enumerate(nodes)))

    strategy = str(_header_value(loaded, "select") or DEFAULT_STRATEGY)
    selection = select_candidate(outcomes, strategy=strategy)
    if selection.chosen is not None:
        context[loaded.orchestration_id or "__round_robin__"] = selection.chosen.output
    return selection, context


async def _run_debate_document(
    loaded: LoadedOrchestration,
    runner: Callable[[Node, dict[str, Any]], Awaitable[Any]],
    *,
    context: dict[str, Any],
) -> DebateResult:
    """Document-level debate: graph nodes are tagged ``pro`` / ``con`` / ``arbiter``."""
    graph = loaded.definition.to_graph()
    pro = _role_node(graph, ROLE_PRO)
    con = _role_node(graph, ROLE_CON)
    arbiter = _role_node(graph, ROLE_ARBITER)
    if pro is None or con is None:
        raise DebateError("debate 模式需要标记 role=pro 与 role=con 的节点")
    if _header_value(loaded, "arbiter") and arbiter is None:
        raise DebateError("debate 声明了 arbiter 但图中无 role=arbiter 节点（加载期 fail-closed）")

    max_rounds = _header_value(loaded, "max_rounds")
    convergence_threshold = float(_header_value(loaded, "convergence_threshold") or 0.8)
    similarity_threshold = float(_header_value(loaded, "similarity_threshold") or 0.9)

    host = Node(id=loaded.orchestration_id or "__debate__", mode=MODE_DEBATE, payload={})
    result = await run_debate(
        host,
        runner,
        context=context,
        orchestration_id=loaded.orchestration_id or "",
        pro_node=pro,
        con_node=con,
        arbiter_node=arbiter,
        max_rounds=max_rounds,
        convergence_threshold=convergence_threshold,
        similarity_threshold=similarity_threshold,
    )
    context[host.id] = result
    return result


def _role_node(graph: Graph, role: str) -> Node | None:
    for node in graph.nodes.values():
        if str((node.payload or {}).get("role") or "") == role:
            return node
    return None


def wrap_node_runner(
    runner: Callable[[Node, dict[str, Any]], Awaitable[Any]],
    *,
    orchestration_id: str = "",
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> NodeRunner:
    """Wrap a runner so a ``round_robin`` / ``debate`` *child* node dispatches itself.

    Used when these modes appear inside a ``graph`` execution (FR-009 / R-16): the
    wrapper intercepts the node by its ``mode``, runs the dedicated protocol, and
    hands back a single output (one atomic success-or-failure). All other nodes are
    passed through untouched, so existing behaviour is unchanged.
    """

    async def wrapped(node: Node, ctx: dict[str, Any]) -> Any:
        if node.mode == MODE_ROUND_ROBIN:
            specs = parse_instances(node.payload.get("instances"))
            strategy = str(node.payload.get("select") or DEFAULT_STRATEGY)
            selection, payload = await run_round_robin(
                node,
                runner,
                context=ctx,
                instances=specs,
                strategy=strategy,
                max_concurrency=int(node.payload.get("max_concurrency") or max_concurrency),
            )
            if selection.chosen is None:
                raise RoundRobinError(f"节点 {node.id} 全部候选失败：{payload.get('errors')}")
            return selection.chosen.output

        if node.mode == MODE_DEBATE:
            pro_id = str((node.payload or {}).get("pro") or "")
            con_id = str((node.payload or {}).get("con") or "")
            arbiter_id = str((node.payload or {}).get("arbiter") or "")
            pro = Node(id=pro_id, mode=MODE_DEBATE, payload={}) if pro_id else None
            con = Node(id=con_id, mode=MODE_DEBATE, payload={}) if con_id else None
            arbiter = Node(id=arbiter_id, mode=MODE_DEBATE, payload={}) if arbiter_id else None
            result = await run_debate(
                node,
                runner,
                context=ctx,
                orchestration_id=orchestration_id,
                pro_node=pro,
                con_node=con,
                arbiter_node=arbiter,
                max_rounds=node.payload.get("max_rounds"),
                convergence_threshold=float(node.payload.get("convergence_threshold") or 0.8),
                similarity_threshold=float(node.payload.get("similarity_threshold") or 0.9),
            )
            return result.as_payload()

        return await runner(node, ctx)

    return wrapped
