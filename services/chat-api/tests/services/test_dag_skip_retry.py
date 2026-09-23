"""010 T013-T015 (conditional skip + skip traceability) + T016-T017 (node retry) tests."""

from __future__ import annotations

import pytest

from app.orchestration.graph import Edge, Graph, Node
from app.services.dag.retry import RetryPolicy, backoff_delay, policy_from_node, run_node_with_retry
from app.services.dag.skip import DownstreamPolicy, SkipDecision, evaluate_skip, skip_trace_document


def _chain_graph() -> Graph:
    graph = Graph(
        nodes=[
            Node("a", condition={"op": "==", "left": {"var": "total"}, "right": 0}),
            Node("b"),
            Node("c"),
            Node("d"),
        ],
        edges=[Edge("a", "b"), Edge("b", "c"), Edge("c", "d")],
    )
    return graph


# --- T013-T015 conditional skip ----------------------------------------------


def test_skip_condition_true_skips_node():
    graph = _chain_graph()
    decision = evaluate_skip(graph, "a", context={"total": 0})
    assert decision.skipped is True
    assert decision.reason == "condition_true"


def test_skip_condition_false_runs_node():
    graph = _chain_graph()
    decision = evaluate_skip(graph, "a", context={"total": 5})
    assert decision.skipped is False
    assert decision.reason == "condition_false"


def test_skip_no_condition_runs():
    graph = _chain_graph()
    decision = evaluate_skip(graph, "b", context={})
    assert decision.skipped is False
    assert decision.reason == "no_condition"


def test_skip_syntax_error_fails_closed():
    graph = Graph(
        nodes=[
            Node("a", condition={"op": "nope", "left": {"var": "x"}, "right": 0}),
            Node("b"),
        ],
        edges=[Edge("a", "b")],
    )
    decision = evaluate_skip(graph, "a", context={"x": 0})
    assert decision.skipped is True
    assert decision.reason == "syntax_error"
    assert decision.error
    # US3 acceptance 3: a syntax error is a fail-closed skip, not a silent run.


def test_skip_propagate_marks_downstream():
    graph = _chain_graph()
    decision = evaluate_skip(
        graph, "a", context={"total": 0}, downstream_policy=DownstreamPolicy.PROPAGATE
    )
    assert decision.skipped is True
    # b/c/d are transitive downstream of a -> all affected
    assert set(decision.affected_downstream) == {"b", "c", "d"}


def test_skip_continue_keeps_downstream_runnable():
    graph = _chain_graph()
    decision = evaluate_skip(
        graph, "a", context={"total": 0}, downstream_policy=DownstreamPolicy.CONTINUE
    )
    assert decision.skipped is True
    # policy=continue -> only "a" is skipped, downstream stays runnable
    assert decision.affected_downstream == []


# --- T014 skip traceability ---------------------------------------------------


def test_skip_trace_documents_reason_and_affected():
    graph = _chain_graph()
    decision = evaluate_skip(
        graph, "a", context={"total": 0}, downstream_policy=DownstreamPolicy.PROPAGATE
    )
    doc = skip_trace_document(decision)
    assert doc["node_id"] == "a"
    assert doc["skipped"] is True
    # 跳过追溯：reason = 求值结果 + 被跳过的下游标记 (T014)
    assert doc["reason"] == "condition_true"
    assert set(doc["affected_downstream"]) == {"b", "c", "d"}
    assert doc["result"] is True


def test_skip_trace_false_condition_no_downstream():
    graph = _chain_graph()
    decision = evaluate_skip(graph, "a", context={"total": 5})
    doc = skip_trace_document(decision)
    assert doc["skipped"] is False
    assert doc["affected_downstream"] == []


# --- T016-T017 node-level retry + layering -----------------------------------


def test_backoff_delay_exponential():
    policy = RetryPolicy(max_attempts=5, base_seconds=2.0, factor=2.0, cap_seconds=60.0)
    assert policy.delay_for(1) == 2.0
    assert policy.delay_for(2) == 4.0
    assert policy.delay_for(3) == 8.0
    assert policy.delay_for(4) == 16.0
    assert backoff_delay(1) == 2.0
    # cap bounds the growth
    capped = RetryPolicy(base_seconds=30.0, factor=2.0, cap_seconds=60.0)
    assert capped.delay_for(4) == 60.0


def test_policy_from_node_reads_retry_config():
    node = Node("n", retry={"max_attempts": 5, "base_seconds": 1.0, "factor": 3.0})
    policy = policy_from_node(node)
    assert policy.max_attempts == 5
    assert policy.base_seconds == 1.0
    assert policy.factor == 3.0
    assert policy.delay_for(1) == 1.0
    assert policy.delay_for(2) == 3.0


def test_node_retry_succeeds_after_failures():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    delays: list[float] = []
    result = run_node_with_retry(
        "n1", flaky,
        policy=RetryPolicy(max_attempts=3),
        sleep=lambda d: delays.append(d),
    )
    assert result.succeeded is True
    assert result.attempts == 3
    # two backoffs before the 3rd attempt
    assert len(delays) == 2
    assert result.final_result == "ok"


def test_node_retry_exhausts_and_reports_error():
    async def always_fail():
        raise RuntimeError("permanent")

    result = run_node_with_retry("n2", always_fail, policy=RetryPolicy(max_attempts=2))
    assert result.succeeded is False
    assert result.exhausted is True
    assert result.attempts == 2
    assert isinstance(result.error, RuntimeError)


def test_node_retry_layering_no_model_backoff_repeat():
    # T017 分层不重复: when delegate_model_backoff=True, the node layer only
    # retries the node and does NOT re-implement model-level backoff.
    policy = RetryPolicy(max_attempts=2, delegate_model_backoff=True)
    assert policy.delegate_model_backoff is True
    attempts: list[int] = []

    async def ok():
        return "done"

    result = run_node_with_retry(
        "n3", ok, policy=policy, on_attempt=lambda nid, attempt, err: attempts.append(attempt)
    )
    assert result.succeeded is True
    assert attempts == [1]
    # no retries happened, no model-backoff duplication at this layer.


def test_node_retry_records_each_attempt():
    attempts: list[int] = []

    async def ok():
        return "done"

    run_node_with_retry(
        "n4",
        ok,
        policy=RetryPolicy(max_attempts=3),
        on_attempt=lambda nid, attempt, err: attempts.append(attempt),
    )
    assert attempts == [1]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
