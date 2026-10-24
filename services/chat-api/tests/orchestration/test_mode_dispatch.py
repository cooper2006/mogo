"""Dispatch + loader integration tests for the 044 modes (T002/T008/T014/T015).

The loader is the fail-closed gate (FR-007 / R-11): unsupported modes and broken
debate/round_robin shapes must raise ``OrchestrationLoadError`` at load time.
``execute_orchestration`` keeps the 010 modes bit-for-bit and adds the two new
document-level executors; ``wrap_node_runner`` lets a round_robin/debate node act
as an atomic child inside a ``graph`` execution.
"""

from __future__ import annotations

import pytest

from app.orchestration.dispatch import execute_orchestration, wrap_node_runner
from app.orchestration.graph import Node
from app.orchestration.loader import OrchestrationLoadError, load_orchestration_document
from app.orchestration.round_robin import SelectionResult


def _doc(mode="graph", nodes=None, header=None) -> dict:
    return {
        "orchestration": {"id": "o1", "mode": mode, **(header or {})},
        "nodes": nodes or [{"id": "a", "mode": mode, "payload": {}}],
    }


# --- loader fail-closed gates ------------------------------------------------

def test_load_round_robin_document_ok() -> None:
    loaded = load_orchestration_document(
        _doc(
            "round_robin",
            nodes=[
                {"id": "a", "instances": [{"model": "m1", "label": "fast"}, {"model": "m2"}]},
            ],
            header={"max_concurrency": 3},
        )
    )
    assert loaded.mode == "round_robin"
    assert loaded.max_concurrency == 3
    assert loaded.definition.nodes[0]["payload"]["instances"]


def test_load_round_robin_rejects_node_level_keys() -> None:
    with pytest.raises(OrchestrationLoadError, match="may not override"):
        load_orchestration_document(
            _doc("round_robin", nodes=[{"id": "a", "mode": "round_robin", "instances": [{"retry": {"a": 1}}]}])
        )


def test_load_debate_node_requires_pro_and_con() -> None:
    with pytest.raises(OrchestrationLoadError, match="requires both 'pro' and 'con'"):
        load_orchestration_document(
            _doc("graph", nodes=[{"id": "a", "mode": "debate", "payload": {"pro": "p"}}])
        )


def test_load_debate_rejects_missing_arbiter_node() -> None:
    with pytest.raises(OrchestrationLoadError, match="does not exist"):
        load_orchestration_document(
            _doc(
                "graph",
                nodes=[
                    {"id": "a", "mode": "debate", "payload": {"pro": "p", "con": "c", "arbiter": "ghost"}},
                    {"id": "p"},
                    {"id": "c"},
                ],
            )
        )


def test_load_debate_document_requires_role_nodes() -> None:
    with pytest.raises(OrchestrationLoadError, match="role=pro and role=con"):
        load_orchestration_document(
            _doc("debate", nodes=[{"id": "a", "payload": {"role": "pro"}}])
        )


def test_load_debate_document_accepts_valid_roles() -> None:
    loaded = load_orchestration_document(
        _doc(
            "debate",
            nodes=[
                {"id": "a", "payload": {"role": "pro"}},
                {"id": "b", "payload": {"role": "con"}},
                {"id": "j", "payload": {"role": "arbiter"}},
            ],
            header={"arbiter": "j", "max_rounds": 2},
        )
    )
    assert loaded.mode == "debate"
    assert loaded.orchestration_id == "o1"


def test_load_debate_document_arbiter_declared_but_absent_fails() -> None:
    with pytest.raises(OrchestrationLoadError, match="no role=arbiter node exists"):
        load_orchestration_document(
            _doc(
                "debate",
                nodes=[
                    {"id": "a", "payload": {"role": "pro"}},
                    {"id": "b", "payload": {"role": "con"}},
                ],
                header={"arbiter": "judge"},
            )
        )


def test_load_unknown_mode_fails_closed() -> None:
    with pytest.raises(OrchestrationLoadError, match="unsupported orchestration mode: 'bogus'"):
        load_orchestration_document(_doc("bogus"))


def test_load_unknown_node_mode_fails_closed() -> None:
    with pytest.raises(OrchestrationLoadError, match="unsupported node mode on 'a'"):
        load_orchestration_document(
            _doc("graph", nodes=[{"id": "a", "mode": "weird"}])
        )


# --- document-level execution ------------------------------------------------

@pytest.mark.asyncio
async def test_execute_graph_keeps_existing_behaviour() -> None:
    loaded = load_orchestration_document(
        _doc("graph", nodes=[{"id": "a"}, {"id": "b", "depends_on": ["a"]}])
    )

    async def runner(node, context):
        context.setdefault("order", []).append(node.id)
        return f"out:{node.id}"

    result = await execute_orchestration(loaded, runner, context={})
    assert result.context["order"] == ["a", "b"]
    assert result.outcomes["a"].state == "completed"


@pytest.mark.asyncio
async def test_execute_round_robin_document_selects_best_score() -> None:
    loaded = load_orchestration_document(
        _doc(
            "round_robin",
            nodes=[
                {"id": "a", "payload": {"score_hint": True}},
                {"id": "b"},
            ],
            header={"select": "highest_score", "max_concurrency": 2},
        )
    )

    async def runner(node, context):
        return {"text": f"{node.id}", "score": 0.3 if node.id == "a" else 0.9}

    result = await execute_orchestration(loaded, runner, context={})
    selection, _ctx = result
    assert isinstance(selection, SelectionResult)
    assert selection.chosen is not None and selection.chosen.label == "b"


@pytest.mark.asyncio
async def test_execute_round_robin_unknown_mode_never_silently_downgrades() -> None:
    # Direct document dispatch of a declared-but-unknown mode cannot happen after
    # loading, but a hand-built LoadedOrchestration must still fail closed.
    loaded = load_orchestration_document(_doc("graph", nodes=[{"id": "a"}]))
    loaded.mode = "bogus"  # bypass loader on purpose
    with pytest.raises(OrchestrationLoadError, match="未知编排模式"):
        await execute_orchestration(loaded, lambda n, c: None, context={})


@pytest.mark.asyncio
async def test_execute_debate_document() -> None:
    loaded = load_orchestration_document(
        _doc(
            "debate",
            nodes=[
                {"id": "a", "payload": {"role": "pro"}},
                {"id": "b", "payload": {"role": "con"}},
            ],
            header={"max_rounds": 2},
        )
    )

    async def runner(node, context):
        return {"text": f"{node.id}-{context['debate']['round']}"}

    result = await execute_orchestration(loaded, runner, context={})
    assert result.conclusion == "a-2"
    assert result.applied_rounds == 2


# --- node-level wrapper ------------------------------------------------------

@pytest.mark.asyncio
async def test_wrap_node_runner_runs_round_robin_child() -> None:
    child = Node(
        id="t",
        mode="round_robin",
        payload={"instances": [{"label": "a"}, {"label": "b"}], "select": "highest_score"},
    )

    async def inner(node, context):
        return {"text": node.payload["instance_label"], "score": 0.5}

    wrapped = wrap_node_runner(inner)
    output = await wrapped(child, {})
    assert isinstance(output, dict) and output["text"] == "a"


@pytest.mark.asyncio
async def test_wrap_node_runner_fails_when_all_candidates_fail() -> None:
    child = Node(id="t", mode="round_robin", payload={"instances": [{"label": "a"}]})

    async def inner(node, context):
        raise RuntimeError("nope")

    with pytest.raises(Exception, match="全部候选失败"):
        await wrap_node_runner(inner)(child, {})


@pytest.mark.asyncio
async def test_wrap_node_runner_passes_through_other_nodes() -> None:
    async def inner(node, context):
        return f"plain:{node.id}"

    wrapped = wrap_node_runner(inner)
    assert await wrapped(Node(id="x"), {}) == "plain:x"
