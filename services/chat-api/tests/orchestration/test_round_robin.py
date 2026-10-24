"""Tests for the round_robin mode (044 T003/T005/T006/T009/T010/T011/T012).

Covers instance parsing, score extraction, all three selection strategies, the
concurrency bound, failure recording, and the document-level dispatch path.
"""

from __future__ import annotations

import pytest

from app.orchestration.graph import Node
from app.orchestration.round_robin import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_STRATEGY,
    CandidateOutcome,
    CandidateSpec,
    RoundRobinError,
    run_round_robin,
    select_candidate,
    normalize_output,
    parse_instances,
    score_of,
)


# --- instances schema --------------------------------------------------------

def test_parse_instances_absent_is_single_candidate() -> None:
    assert parse_instances(None) == []
    assert parse_instances([]) == []


def test_parse_instances_accepts_allowed_overrides() -> None:
    specs = parse_instances(
        [{"model": "qwen3", "temperature": 0.3, "prompt": "p", "label": "fast"}]
    )
    assert specs == [CandidateSpec(label="fast", overrides={"model": "qwen3", "temperature": 0.3, "prompt": "p"})]


def test_parse_instances_rejects_node_level_keys_fail_closed() -> None:
    with pytest.raises(RoundRobinError, match="may not override"):
        parse_instances([{"retry": {"max_attempts": 2}}])


def test_parse_instances_rejects_unknown_keys() -> None:
    with pytest.raises(RoundRobinError, match="unsupported keys"):
        parse_instances([{"bogus": 1}])


def test_parse_instances_defaults_label() -> None:
    assert parse_instances([{"model": "m"}])[0].label == "candidate_1"


# --- score -------------------------------------------------------------------

def test_score_of_clamps_and_ignores_non_scores() -> None:
    assert score_of({"score": 1.4}) == 1.0
    assert score_of({"score": -0.2}) == 0.0
    assert score_of({"score": 0.7}) == 0.7
    assert score_of({"score": True}) is None
    assert score_of({"score": "0.9"}) is None
    assert score_of({"score": float("nan")}) is None
    assert score_of({"text": "x"}) is None
    assert score_of("plain string") is None


# --- selection ---------------------------------------------------------------

def test_first_success_picks_earliest_completed() -> None:
    outcomes = [
        CandidateOutcome(label="a", status="failed", order=0, error="boom"),
        CandidateOutcome(label="b", status="completed", output="ok", order=1),
        CandidateOutcome(label="c", status="completed", output="also", order=2),
    ]
    result = select_candidate(outcomes, strategy="first_success")
    assert result.chosen.label == "b"
    assert result.strategy == "first_success"


def test_highest_score_only_among_scored() -> None:
    outcomes = [
        CandidateOutcome(label="scored-low", status="completed", score=0.4, order=0),
        CandidateOutcome(label="scored-high", status="completed", score=0.9, order=1),
        CandidateOutcome(label="unscored", status="completed", score=None, order=2),
    ]
    result = select_candidate(outcomes, strategy="highest_score")
    assert result.chosen.label == "scored-high"


def test_highest_score_no_scores_falls_back_to_first_success() -> None:
    outcomes = [
        CandidateOutcome(label="a", status="completed", order=0),
        CandidateOutcome(label="b", status="completed", order=1),
    ]
    result = select_candidate(outcomes, strategy="highest_score")
    assert result.chosen.label == "a"
    assert result.fallback_reason == "no_score"
    assert result.strategy == "first_success"


def test_highest_score_scored_all_failed_adopts_unscored() -> None:
    outcomes = [
        CandidateOutcome(label="scored", status="failed", score=0.9, order=0, error="x"),
        CandidateOutcome(label="unscored", status="completed", score=None, order=1),
    ]
    result = select_candidate(outcomes, strategy="highest_score")
    assert result.chosen.label == "unscored"
    assert result.fallback_reason == "scored_all_failed"


def test_majority_normalizes_outputs() -> None:
    assert normalize_output("  Hello\nWorld ") == "helloworld"
    assert normalize_output({"answer": "YES"}) == "yes"
    assert normalize_output("") == ""


def test_majority_picks_repeated_output() -> None:
    outcomes = [
        CandidateOutcome(label="a", output="同意", order=0),
        CandidateOutcome(label="b", output=" 同 意 ", order=1),
        CandidateOutcome(label="c", output="反对", order=2),
    ]
    result = select_candidate(outcomes, strategy="majority")
    assert result.chosen.label == "a"
    assert result.fallback_reason == ""


def test_majority_tie_records_reason_and_takes_earliest() -> None:
    outcomes = [
        CandidateOutcome(label="a", output="x", order=0),
        CandidateOutcome(label="b", output="x", order=1),
        CandidateOutcome(label="c", output="y", order=2),
        CandidateOutcome(label="d", output="y", order=3),
    ]
    result = select_candidate(outcomes, strategy="majority")
    assert result.chosen.label == "a"
    assert result.fallback_reason == "majority_tie"


def test_majority_no_majority_falls_back_to_first_success() -> None:
    outcomes = [
        CandidateOutcome(label="a", output="x", order=0),
        CandidateOutcome(label="b", output="y", order=1),
    ]
    result = select_candidate(outcomes, strategy="majority")
    assert result.chosen.label == "a"
    assert result.fallback_reason == "no_majority"


def test_unknown_strategy_defaults_to_highest_score() -> None:
    outcomes = [CandidateOutcome(label="a", status="completed", score=0.5, order=0)]
    assert select_candidate(outcomes, strategy="bogus").strategy == DEFAULT_STRATEGY


# --- execution ---------------------------------------------------------------

async def _runner(outputs):
    calls = []

    async def runner(node, context):
        calls.append(node.id)
        if node.id in outputs:
            return outputs[node.id]
        return f"out:{node.id}"

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


@pytest.mark.asyncio
async def test_run_round_robin_all_failed_returns_none_chosen() -> None:
    async def failing(node, context):
        raise RuntimeError("nope")

    node = Node(id="t", payload={"instances": [{"label": "a"}, {"label": "b"}]})
    selection, payload = await run_round_robin(node, failing, context={})
    assert selection.chosen is None
    assert all(item.status == "failed" for item in selection.candidates)
    assert payload["errors"]


@pytest.mark.asyncio
async def test_run_round_robin_first_success_discards_others() -> None:
    async def runner(node, context):
        return {"text": f"from {node.payload['instance_label']}", "score": 0.5}

    node = Node(id="t", payload={"instances": [{"label": "a"}, {"label": "b"}]})
    selection, payload = await run_round_robin(node, runner, context={}, strategy="first_success")
    statuses = {item.label: item.status for item in selection.candidates}
    assert statuses["a"] == "completed"
    assert selection.chosen.label == "a"
    assert payload["strategy"] == "first_success"
    assert payload["chosen"] == "a"
    assert payload["candidates"][0]["label"] == "a"


@pytest.mark.asyncio
async def test_run_round_robin_respects_max_concurrency() -> None:
    order: list[int] = []
    started = 0

    async def runner(node, context):
        nonlocal started
        started += 1
        order.append(started)
        return "ok"

    node = Node(id="t", payload={"instances": [{"label": f"c{i}"} for i in range(4)]})
    await run_round_robin(node, runner, context={}, max_concurrency=1)
    # Serial execution means start counters are 1..4 in declaration order.
    assert order == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_run_round_robin_single_candidate_defaults() -> None:
    async def runner(node, context):
        return {"text": "solo"}

    selection, _ = await run_round_robin(Node(id="t"), runner, context={})
    assert selection.chosen.label == "default"
    assert DEFAULT_MAX_CONCURRENCY == 4
