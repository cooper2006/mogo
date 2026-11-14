"""Tests for supervisor/hybrid modes + orchestration registry (010 T003/T011/T012)."""

from __future__ import annotations

import pytest

from app.orchestration.graph import Node
from app.orchestration.registry import (
    DEFAULT_DEFINITION_VERSION,
    OrchestrationDefinition,
    OrchestrationRegistry,
    RegistryError,
)
from app.orchestration.supervisor import (
    DEFAULT_CHILD_FAILURE_THRESHOLD,
    Supervisor,
    run_hybrid,
)


async def _ok_child(node, context):
    return f"child:{node.id}"


# --- supervisor --------------------------------------------------------------

@pytest.mark.asyncio
async def test_supervisor_aggregates_successful_children() -> None:
    children = [Node(id="c1"), Node(id="c2")]
    result = await Supervisor("sup", children).run(_ok_child)
    assert result.ok is True
    assert result.successful_children == ["c1", "c2"]
    assert result.aggregated["successCount"] == 2


@pytest.mark.asyncio
async def test_supervisor_all_children_failed_fails() -> None:
    children = [Node(id="c1"), Node(id="c2")]

    async def failing(node, context):
        raise RuntimeError("child boom")

    result = await Supervisor("sup", children).run(failing)
    assert result.supervisor_failed is True
    assert result.failed_children == ["c1", "c2"]


@pytest.mark.asyncio
async def test_supervisor_partial_failure_still_ok_by_default() -> None:
    children = [Node(id="c1"), Node(id="c2")]

    async def partial(node, context):
        if node.id == "c1":
            raise RuntimeError("boom")
        return "fine"

    result = await Supervisor("sup", children).run(partial)
    assert result.ok is True  # default threshold requires ALL children to fail
    assert result.failed_children == ["c1"]


@pytest.mark.asyncio
async def test_supervisor_threshold_makes_partial_failure_fail() -> None:
    children = [Node(id="c1"), Node(id="c2")]

    async def partial(node, context):
        if node.id == "c1":
            raise RuntimeError("boom")
        return "fine"

    result = await Supervisor("sup", children, child_failure_threshold=0.5).run(partial)
    assert result.supervisor_failed is True
    assert "阈值" in result.reason


@pytest.mark.asyncio
async def test_supervisor_itself_failing_fails_whole_run() -> None:
    children = [Node(id="c1")]
    result = await Supervisor("sup", children).run(
        _ok_child, supervisor_ok=False, supervisor_error="supervisor down"
    )
    assert result.supervisor_failed is True
    assert "监督节点失败" in result.reason


@pytest.mark.asyncio
async def test_supervisor_without_children_fails() -> None:
    result = await Supervisor("sup", []).run(_ok_child)
    assert result.supervisor_failed is True
    assert "无子节点" in result.reason


def test_default_threshold_is_all_children() -> None:
    assert DEFAULT_CHILD_FAILURE_THRESHOLD == 1.0


# --- hybrid ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_runs_sequential_then_parallel() -> None:
    order: list[str] = []

    async def runner(node_id, context):
        order.append(node_id)
        return f"out:{node_id}"

    result = await run_hybrid(
        sequential_ids=["s1", "s2"],
        parallel_ids=["p1", "p2"],
        runner=runner,
    )
    assert result["order"][:2] == ["s1", "s2"]           # sequential prefix first
    assert set(result["order"][2:]) == {"p1", "p2"}      # parallel stage after
    assert result["context"]["p1"] == "out:p1"


@pytest.mark.asyncio
async def test_hybrid_passes_sequential_output_to_parallel() -> None:
    async def runner(node_id, context):
        if node_id == "p1":
            return f"saw:{context.get('s1')}"
        return "seq"

    result = await run_hybrid(sequential_ids=["s1"], parallel_ids=["p1"], runner=runner)
    assert result["context"]["p1"] == "saw:seq"


# --- registry ----------------------------------------------------------------

def test_definition_requires_id() -> None:
    with pytest.raises(RegistryError):
        OrchestrationDefinition(orchestration_id="")


def test_definition_builds_graph() -> None:
    definition = OrchestrationDefinition(
        orchestration_id="o1",
        nodes=[{"id": "a"}, {"id": "b"}],
        edges=[{"source": "a", "target": "b"}],
    )
    graph = definition.to_graph()
    assert set(graph.nodes) == {"a", "b"}
    assert graph.dependencies("b") == ["a"]


def test_definition_rejects_dangling_edge() -> None:
    definition = OrchestrationDefinition(
        orchestration_id="o1",
        nodes=[{"id": "a"}],
        edges=[{"source": "a", "target": "ghost"}],
    )
    with pytest.raises(RegistryError):
        definition.validate()


def test_definition_rejects_malformed_condition() -> None:
    definition = OrchestrationDefinition(
        orchestration_id="o1",
        nodes=[{"id": "a", "condition": {"op": "explode"}}],
    )
    with pytest.raises(RegistryError):
        definition.validate()


def test_definition_allows_variable_conditions() -> None:
    definition = OrchestrationDefinition(
        orchestration_id="o1",
        nodes=[{"id": "a", "condition": {"op": "==", "left": {"var": "x"}, "right": 1}}],
    )
    definition.validate()  # variables are unresolvable at definition time, not invalid


def test_update_bumps_version_and_archives() -> None:
    definition = OrchestrationDefinition(orchestration_id="o1", nodes=[{"id": "a"}])
    assert definition.version == DEFAULT_DEFINITION_VERSION
    new_version = definition.update(nodes=[{"id": "a"}, {"id": "b"}])
    assert new_version == 2
    assert len(definition.versions) == 1


def test_registry_register_and_history() -> None:
    registry = OrchestrationRegistry()
    definition = OrchestrationDefinition(orchestration_id="o1", nodes=[{"id": "a"}])
    registry.register(definition)
    definition.update(nodes=[{"id": "a"}, {"id": "b"}])
    assert registry.list_ids() == ["o1"]
    assert len(registry.history("o1")) == 1


def test_registry_rejects_invalid_definition() -> None:
    registry = OrchestrationRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            OrchestrationDefinition(orchestration_id="o1", nodes=[{"id": "a"}], edges=[{"source": "a", "target": "x"}])
        )
