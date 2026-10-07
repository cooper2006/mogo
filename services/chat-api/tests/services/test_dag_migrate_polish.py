"""010 T018-T022 tests: builder dual-track migration, equivalence, concurrency guard, versioning, contracts."""

from __future__ import annotations

import asyncio

import pytest

from app.services.dag.builder_migrate import (
    BuilderPath,
    builder_equivalent,
    content_plan_dag,
    run_content_plan_dag,
)


# --- T018 dual-track migration -----------------------------------------------


def test_content_plan_dag_shape():
    async def semantic_build(ctx):
        return {"mode": "semantic"}

    async def structured_build(ctx):
        return {"mode": "structured"}

    async def fallback_build(ctx):
        return {"mode": "fallback"}

    semantic = BuilderPath("semantic", semantic_build)
    structured = BuilderPath("structured", structured_build)
    fallback = BuilderPath("fallback", fallback_build)

    def merge(incoming, fallback_plan, ctx):
        return incoming if incoming is not None else fallback_plan

    dag = content_plan_dag({
        "semantic": semantic,
        "structured": structured,
        "fallback": fallback,
    })
    assert "semantic" in dag.nodes
    assert "merge" in dag.nodes

    result = asyncio.run(
        run_content_plan_dag(
            dag,
            semantic=semantic,
            structured=structured,
            fallback=fallback,
            merge=merge,
            context={},
        )
    )
    assert result["dual_track"] is True
    # semantic wins when it succeeds (mirrors the legacy control flow)
    assert result["merged"] == {"mode": "semantic"}


def test_content_plan_dag_falls_back_when_semantic_fails():
    async def failing(_ctx):
        raise RuntimeError("semantic broken")

    semantic = BuilderPath("semantic", failing)

    async def structured_ok(ctx):
        return {"mode": "structured"}

    structured = BuilderPath("structured", structured_ok)

    async def fallback_ok(ctx):
        return {"mode": "fallback"}

    fallback = BuilderPath("fallback", fallback_ok)

    def merge(incoming, fallback_plan, ctx):
        return incoming if incoming is not None else fallback_plan

    dag = content_plan_dag({"semantic": semantic, "structured": structured, "fallback": fallback})
    result = asyncio.run(
        run_content_plan_dag(
            dag,
            semantic=semantic,
            structured=structured,
            fallback=fallback,
            merge=merge,
            context={},
        )
    )
    # semantic failed -> structured is used (mirrors legacy degradation)
    assert result["merged"] == {"mode": "structured"}
    assert result["semantic"] is None


# --- T019 equivalence (0-breakage regression guard) --------------------------


def test_builder_equivalent_same_keys():
    legacy_plan = {"execution_mode": "sectional_compose", "sections": ["a", "b"], "title": "x"}
    dag_result = {
        "merged": {"execution_mode": "sectional_compose", "sections": ["a", "b"], "title": "x", "extra": 1},
        "dual_track": True,
    }
    # Same key fields -> equivalent (0-breakage)
    assert builder_equivalent(legacy_plan, dag_result) is True


def test_builder_equivalent_differs_when_key_field_changes():
    legacy_plan = {"execution_mode": "inline", "sections": ["a"], "title": "x"}
    dag_result = {
        "merged": {"execution_mode": "sectional_compose", "sections": ["a"], "title": "x"},
        "dual_track": True,
    }
    # execution_mode differs -> NOT equivalent
    assert builder_equivalent(legacy_plan, dag_result) is False


def test_builder_equivalent_with_plan_getter():
    from types import SimpleNamespace

    class Spec:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    legacy = Spec(execution_mode="inline", sections=["a"], title="x")
    merged = Spec(execution_mode="inline", sections=["a"], title="x")

    def getter(obj):
        return (obj.execution_mode, tuple(obj.sections), obj.title)

    assert builder_equivalent(legacy, {"merged": merged, "dual_track": True}, plan_getter=getter) is True
    assert builder_equivalent(legacy, {"merged": Spec(execution_mode="other", sections=["a"], title="x"), "dual_track": True}, plan_getter=getter) is False


def test_builder_equivalent_missing_merged_is_false():
    assert builder_equivalent({"a": 1}, {"dual_track": True}) is False


# --- T020 cross-layer concurrency budget guard --------------------------------
#
# QA R5: the two tests below used to build their own local counter / `_Budget`
# class and assert on *those*. They passed with the orchestration package
# deleted — they verified a Python language property, not this feature. They now
# drive the real DagEngine.
#
# Honest boundary: the budget implemented here is the **node-level** one
# (`DagEngine.max_concurrency`). The cross-DAG budget coordinated with the 007
# gateway (FR-12) is still not implemented — there is no `dag_max_concurrency`
# setting anywhere — so this file no longer claims to cover it.


def test_dag_engine_bounds_node_concurrency():
    """The real engine never runs more nodes at once than its budget allows."""
    from app.orchestration.engine import DagEngine
    from app.orchestration.graph import Graph, Node

    in_flight = {"now": 0, "peak": 0}

    async def runner(node, _ctx):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0.02)
        in_flight["now"] -= 1
        return node.id

    graph = Graph()
    for index in range(8):                      # 8 independent nodes, budget 2
        graph.add_node(Node(id=f"n{index}"))

    result = asyncio.run(DagEngine(max_concurrency=2).run_graph(graph, runner))

    assert result.succeeded
    assert len(result.outcomes) == 8
    assert in_flight["peak"] <= 2, f"engine exceeded its budget: peak={in_flight['peak']}"
    assert in_flight["peak"] > 1, "the engine serialized everything; the bound is untested"


def test_dag_engine_serializes_at_concurrency_one():
    """A budget of 1 must strictly alternate start/end — never two in flight."""
    from app.orchestration.engine import DagEngine
    from app.orchestration.graph import Graph, Node

    timeline: list[str] = []

    async def runner(node, _ctx):
        timeline.append("start")
        await asyncio.sleep(0.005)
        timeline.append("end")
        return node.id

    graph = Graph()
    for index in range(4):
        graph.add_node(Node(id=f"n{index}"))

    asyncio.run(DagEngine(max_concurrency=1).run_graph(graph, runner))

    assert timeline == ["start", "end"] * 4, f"not serialized: {timeline}"


# --- T021 orchestration definition versioning --------------------------------


def test_definition_version_increment_and_lookup():
    """Updating a definition bumps its version and keeps the old one viewable."""
    from app.orchestration.registry import (
        OrchestrationDefinition,
        OrchestrationRegistry,
    )

    definition = OrchestrationDefinition(
        orchestration_id="demo",
        nodes=[{"id": "a"}],
        edges=[],
    )
    assert definition.version == 1

    registry = OrchestrationRegistry()
    registry.register(definition)
    assert registry.get("demo").version == 1

    new_version = definition.update(nodes=[{"id": "a"}, {"id": "b"}])
    assert new_version == 2
    assert definition.version == 2

    history = registry.history("demo")
    assert len(history) == 1
    assert history[0]["version"] == 1                       # old version archived
    assert [node["id"] for node in history[0]["nodes"]] == ["a"]
    assert [node["id"] for node in definition.nodes] == ["a", "b"]   # live version moved on


def test_registry_keeps_every_version_browsable():
    """Three updates leave versions 1..3 browsable and the live one at 4."""
    from app.orchestration.registry import (
        OrchestrationDefinition,
        OrchestrationRegistry,
    )

    registry = OrchestrationRegistry()
    definition = OrchestrationDefinition(orchestration_id="demo", nodes=[{"id": "a"}])
    registry.register(definition)

    for index in range(3):
        definition.update(nodes=[{"id": f"v{index}"}])

    assert [entry["version"] for entry in registry.history("demo")] == [1, 2, 3]
    assert registry.get("demo").version == 4
    assert registry.list_ids() == ["demo"]


# --- T022 quickstart + contracts ---------------------------------------------


def test_quickstart_and_contract_exist():
    from pathlib import Path

    here = Path(__file__).resolve().parents[3]
    repo_root = here.parent  # services/ -> repo root
    quickstart = repo_root / "specs" / "010-dag-orchestration-engine" / "quickstart.md"
    contract = repo_root / "contracts" / "orchestration.md"
    assert quickstart.exists(), f"missing {quickstart}"
    assert contract.exists(), f"missing {contract}"
    text = quickstart.read_text() + contract.read_text()
    for keyword in ("schema", "sequential", "supervisor", "hybrid", "graph", "skip", "retry"):
        assert keyword in text.lower(), f"quickstart/contract must document {keyword}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
