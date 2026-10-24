"""Tests for the debate mode (044 T004/T007/T010/T011/T012/T013).

Covers round clamping, the three termination conditions, arbiter semantics, and
the failure contract (one side or the arbiter failing fails the debate).
"""

from __future__ import annotations

import pytest

from app.orchestration.debate import (
    ARBITER_ABSENT,
    DEFAULT_CONVERGENCE_THRESHOLD,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_SIMILARITY_THRESHOLD,
    DebateError,
    TERMINATION_ARBITER_CONFIDENCE,
    TERMINATION_MAX_ROUNDS,
    TERMINATION_OUTPUT_CONVERGED,
    clamp_rounds,
    run_debate,
)
from app.orchestration.graph import Node


# --- clamping ----------------------------------------------------------------

def test_clamp_rounds_bounds() -> None:
    assert clamp_rounds(None) == (3, False)
    assert clamp_rounds(3) == (3, False)
    assert clamp_rounds(1) == (1, False)
    assert clamp_rounds(10) == (10, False)
    assert clamp_rounds(0) == (1, True)
    assert clamp_rounds(11) == (10, True)
    assert clamp_rounds("bogus") == (3, False)
    assert DEFAULT_MAX_ROUNDS == 3
    assert DEFAULT_CONVERGENCE_THRESHOLD == 0.8
    assert DEFAULT_SIMILARITY_THRESHOLD == 0.9


# --- run_debate --------------------------------------------------------------

PRO = Node(id="pro", mode="debate")
CON = Node(id="con", mode="debate")


async def _rounds_runner(pro_texts, con_texts):
    state = {"pro_index": 0, "con_index": 0}

    async def runner(node, context):
        if node.id == "pro":
            text = pro_texts[state["pro_index"]]
            state["pro_index"] += 1
        else:
            text = con_texts[state["con_index"]]
            state["con_index"] += 1
        return {"text": text}

    return runner


@pytest.mark.asyncio
async def test_debate_stops_at_max_rounds() -> None:
    runner = await _rounds_runner(["p1", "p2", "p3"], ["c1", "c2", "c3"])
    result = await run_debate(
        Node(id="t", mode="debate"),
        runner,
        context={},
        orchestration_id="oid",
        pro_node=PRO,
        con_node=CON,
        max_rounds=3,
    )
    assert result.termination == TERMINATION_MAX_ROUNDS
    assert len(result.rounds) == 3
    assert result.conclusion == "p3"
    assert result.confidence is None
    assert result.arbiter == ARBITER_ABSENT
    assert result.converged is False


@pytest.mark.asyncio
async def test_debate_converges_on_similar_outputs() -> None:
    runner = await _rounds_runner(["赞成", "赞成"], ["反对", "反对"])
    result = await run_debate(
        Node(id="t", mode="debate"),
        runner,
        context={},
        orchestration_id="oid",
        pro_node=PRO,
        con_node=CON,
        max_rounds=10,
    )
    assert result.termination == TERMINATION_OUTPUT_CONVERGED
    assert len(result.rounds) == 2
    assert result.converged is True


@pytest.mark.asyncio
async def test_debate_arbiter_confidence_terminates() -> None:
    async def runner(node, context):
        if node.id == "arbiter":
            return {"conclusion": "正方占优", "confidence": 0.92}
        return {"text": f"{node.id}:{context['debate']['round']}"}

    result = await run_debate(
        Node(id="t", mode="debate"),
        runner,
        context={},
        orchestration_id="oid",
        pro_node=PRO,
        con_node=CON,
        arbiter_node=Node(id="arbiter", mode="debate"),
        max_rounds=10,
    )
    assert result.termination == TERMINATION_ARBITER_CONFIDENCE
    assert result.conclusion == "正方占优"
    assert result.confidence == 0.92
    assert result.arbiter == "arbiter"
    assert result.converged is True


@pytest.mark.asyncio
async def test_debate_arbiter_below_threshold_keeps_debating() -> None:
    async def runner(node, context):
        if node.id == "arbiter":
            return {"conclusion": "待定", "confidence": 0.4}
        return {"text": f"{node.id}-{context['debate']['round']}"}

    result = await run_debate(
        Node(id="t", mode="debate"),
        runner,
        context={},
        orchestration_id="oid",
        pro_node=PRO,
        con_node=CON,
        arbiter_node=Node(id="arbiter", mode="debate"),
        max_rounds=2,
    )
    assert result.termination == TERMINATION_MAX_ROUNDS
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_debate_fails_when_pro_side_raises() -> None:
    async def runner(node, context):
        if node.id == "pro":
            raise RuntimeError("pro down")
        return "con ok"

    with pytest.raises(DebateError, match="正方节点"):
        await run_debate(
            Node(id="t", mode="debate"), runner, context={}, orchestration_id="o",
            pro_node=PRO, con_node=CON, max_rounds=3,
        )


@pytest.mark.asyncio
async def test_debate_fails_when_arbiter_output_is_not_object() -> None:
    async def runner(node, context):
        if node.id == "arbiter":
            return "just a string"
        return f"{node.id}"

    with pytest.raises(DebateError, match="仲裁节点"):
        await run_debate(
            Node(id="t", mode="debate"), runner, context={}, orchestration_id="o",
            pro_node=PRO, con_node=CON,
            arbiter_node=Node(id="arbiter", mode="debate"), max_rounds=2,
        )


@pytest.mark.asyncio
async def test_debate_requires_pro_and_con() -> None:
    with pytest.raises(DebateError, match="requires both"):
        await run_debate(
            Node(id="t", mode="debate"), _rounds_runner(["p"], ["c"]), context={},
            orchestration_id="o", pro_node=None, con_node=CON, max_rounds=1,
        )


@pytest.mark.asyncio
async def test_debate_context_keys_stay_local() -> None:
    runner = await _rounds_runner(["p1", "p2"], ["c1", "c2"])
    seen: dict[str, object] = {}

    async def capturing(node, context):
        seen[node.id] = dict(context)
        return await runner(node, context)

    shared = {"outer": True}
    await run_debate(
        Node(id="t", mode="debate"), capturing, context=shared,
        orchestration_id="oid", pro_node=PRO, con_node=CON, max_rounds=2,
    )
    # The global context must never be polluted with debate round keys (044 R-4):
    # the runner only sees the caller context, the shared local dict, and the
    # ``debate`` envelope -- never its own freshly-written round key.
    assert "outer" in seen["pro"]
    assert "debate:oid:t:round:2:pro" not in seen["pro"]
    assert "debate:oid:t:round:2:con" not in seen["pro"]
    # The shared local dict may carry *earlier* round keys (that is how the other
    # side reads round n-1, 044 R-4), but it must never leak a future/current key.
    assert "debate:oid:t:round:1:pro" in seen["pro"]


@pytest.mark.asyncio
async def test_debate_reports_clamped_rounds() -> None:
    runner = await _rounds_runner([f"p{i}" for i in range(10)], [f"c{i}" for i in range(10)])
    result = await run_debate(
        Node(id="t", mode="debate"), runner, context={}, orchestration_id="o",
        pro_node=PRO, con_node=CON, max_rounds=99,
    )
    assert result.requested_rounds == 99
    assert result.applied_rounds == 10
    assert result.clamped is True
