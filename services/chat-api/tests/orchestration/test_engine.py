"""Tests for the DAG execution engine (feature 010, US1/US2): engine behaviour."""

from __future__ import annotations

import asyncio

import pytest

from app.orchestration.engine import (
    DEFAULT_MAX_CONCURRENCY,
    DagEngine,
    NodeState,
)
from app.orchestration.graph import Edge, Graph, Node


def _graph(edges, nodes=None, *, conditions=None, ids=None):
    # An edge may be a 1-tuple ("a",) meaning "node a with no edges".
    pairs = [edge for edge in edges if len(edge) == 2]
    lone = [edge[0] for edge in edges if len(edge) == 1]
    node_ids = ids or sorted({item for edge in pairs for item in edge} | set(lone))
    conditions = conditions or {}
    g = Graph(nodes=[Node(id=name, condition=conditions.get(name)) for name in node_ids])
    for source, target in pairs:
        g.add_edge(Edge(source, target))
    return g


async def _ok(node, context):
    return f"out:{node.id}"


# --- graph mode --------------------------------------------------------------

@pytest.mark.asyncio
async def test_runs_all_nodes_in_topological_order() -> None:
    g = _graph([("a", "b"), ("b", "c")])
    engine = DagEngine()
    result = await engine.run_graph(g, _ok)
    assert result.succeeded
    assert result.outcomes["a"].state == NodeState.COMPLETED.value
    assert result.context["c"] == "out:c"


@pytest.mark.asyncio
async def test_context_passes_upstream_output_to_downstream() -> None:
    g = _graph([("a", "b")])

    async def runner(node, context):
        if node.id == "b":
            return f"got:{context.get('a')}"
        return "first"

    result = await DagEngine().run_graph(g, runner)
    assert result.context["b"] == "got:first"


@pytest.mark.asyncio
async def test_node_failure_blocks_downstream_closure() -> None:
    g = _graph([("a", "b"), ("b", "c"), ("c", "d")])

    async def runner(node, context):
        if node.id == "b":
            raise RuntimeError("boom")
        return node.id

    result = await DagEngine().run_graph(g, runner)
    assert result.outcomes["b"].state == NodeState.FAILED.value
    # b's entire downstream closure is blocked, not just the direct child
    assert result.outcomes["c"].state == NodeState.BLOCKED.value
    assert result.outcomes["d"].state == NodeState.BLOCKED.value
    assert "b" in result.failed_nodes
    assert set(result.blocked_nodes) == {"c", "d"}


@pytest.mark.asyncio
async def test_sibling_branch_still_runs_after_failure() -> None:
    g = _graph([("a", "b"), ("a", "c")])

    async def runner(node, context):
        if node.id == "b":
            raise RuntimeError("boom")
        return node.id

    result = await DagEngine().run_graph(g, runner)
    assert result.outcomes["c"].state == NodeState.COMPLETED.value


@pytest.mark.asyncio
async def test_conditional_skip_records_reason() -> None:
    g = _graph([("a", "b")], conditions={"a": {"op": "==", "left": 1, "right": 2}})
    result = await DagEngine().run_graph(g, _ok)
    assert result.outcomes["a"].state == NodeState.SKIPPED.value
    assert "条件" in result.outcomes["a"].reason


@pytest.mark.asyncio
async def test_conditional_true_runs() -> None:
    g = _graph([("a",)], conditions={"a": {"op": "==", "left": 1, "right": 1}})
    result = await DagEngine().run_graph(g, _ok)
    assert result.outcomes["a"].state == NodeState.COMPLETED.value


@pytest.mark.asyncio
async def test_malformed_condition_skips_fail_closed() -> None:
    g = _graph([("a",)], conditions={"a": {"op": "explode"}})
    result = await DagEngine().run_graph(g, _ok)
    assert result.outcomes["a"].state == NodeState.SKIPPED.value
    assert "条件求值失败" in result.outcomes["a"].reason


@pytest.mark.asyncio
async def test_events_recorded_for_each_transition() -> None:
    g = _graph([("a", "b")])
    result = await DagEngine().run_graph(g, _ok)
    events = {(event["node"], event["event"]) for event in result.events}
    assert ("a", "started") in events
    assert ("a", "completed") in events
    assert ("b", "completed") in events


@pytest.mark.asyncio
async def test_concurrency_is_bounded() -> None:
    g = _graph([("a", "d"), ("b", "d"), ("c", "d")], ids=["a", "b", "c", "d"])
    peak = {"n": 0, "current": 0}

    async def runner(node, context):
        peak["current"] += 1
        peak["n"] = max(peak["n"], peak["current"])
        await asyncio.sleep(0.01)
        peak["current"] -= 1
        return node.id

    await DagEngine(max_concurrency=2).run_graph(g, runner)
    assert peak["n"] <= 2


def test_default_concurrency_is_four() -> None:
    assert DEFAULT_MAX_CONCURRENCY == 4


# --- sequential mode ---------------------------------------------------------

@pytest.mark.asyncio
async def test_sequential_runs_one_at_a_time() -> None:
    g = _graph([("a", "b"), ("b", "c")])
    order: list[str] = []

    async def runner(node, context):
        order.append(node.id)
        return node.id

    result = await DagEngine().run_sequential(g, runner)
    assert order == ["a", "b", "c"]
    assert result.succeeded


@pytest.mark.asyncio
async def test_sequential_blocks_downstream_on_failure() -> None:
    g = _graph([("a", "b")])

    async def runner(node, context):
        if node.id == "a":
            raise RuntimeError("boom")
        return node.id

    result = await DagEngine().run_sequential(g, runner)
    assert result.outcomes["a"].state == NodeState.FAILED.value
    assert result.outcomes["b"].state == NodeState.BLOCKED.value
