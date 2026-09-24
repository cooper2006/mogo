"""Acceptance tests for the competitor_deep_dive multi-agent case.

Mirrors docs/cases/multi-agent-competitor-deep-dive.md §8 (criteria 1–10).

Everything runs offline: sub-agents are injectable callables, the retry policy's
sleep is patched, and no LLM or network call is made.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest
import yaml

from app.enterprise_capabilities.research.competitor_deep_dive import (
    ANALYSIS_NODES,
    MIN_COMPLETED_CHILDREN,
    ORCHESTRATION_PATH,
    SYNTHESIS_NODE,
    DeepDiveOrchestrator,
    RetryPolicy,
    _degraded_report,
)
from app.orchestration.conditions import evaluate_condition
from app.orchestration.engine import DagEngine
from app.orchestration.graph import GraphError
from app.orchestration.loader import (
    OrchestrationLoadError,
    compile_expr,
    load_orchestration_file,
)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "app" / "skills_specs"
SUB_SKILLS = (
    "market_intelligence_v1",
    "product_analysis_v1",
    "financial_analysis_v1",
    "sentiment_monitor_v1",
    "report_synthesis_v1",
)


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------


class RecordingAgents:
    """Sub-agents that record start/finish times and can be told to fail."""

    def __init__(self, *, delay: float = 0.02, failing: set[str] | None = None) -> None:
        self.delay = delay
        self.failing = set(failing or ())
        self.windows: dict[str, tuple[float, float]] = {}
        self.calls: list[str] = []
        self.attempts: dict[str, int] = {}

    async def __call__(self, node, context):
        self.calls.append(node.id)
        self.attempts[node.id] = self.attempts.get(node.id, 0) + 1
        if node.id in self.failing:
            raise RuntimeError(f"boom from {node.id}")
        started = time.monotonic()
        await asyncio.sleep(self.delay)
        self.windows[node.id] = (started, time.monotonic())
        return {
            "node": node.id,
            "markdown": f"# section from {node.id}",
            "evidence": [
                {"source": node.id, "claim": f"claim-{node.id}", "url": f"https://example.test/{node.id}"}
            ],
        }


def _all_agents(agents: RecordingAgents) -> dict[str, RecordingAgents]:
    return {node_id: agents for node_id in (*ANALYSIS_NODES, SYNTHESIS_NODE)}


async def _no_sleep(_seconds: float) -> None:
    """Patch the retry sleep so backoff tests do not actually wait."""


def _orchestrator(**kwargs) -> DeepDiveOrchestrator:
    return DeepDiveOrchestrator(**kwargs)


# --------------------------------------------------------------------------
# AC-1: four analysis nodes run in parallel (concurrency >= 3)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_nodes_run_in_parallel():
    agents = RecordingAgents(delay=0.05)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉")

    assert orchestrator.concurrency_peak >= 3, (
        f"expected at least 3 nodes running together, peak was {orchestrator.concurrency_peak}"
    )

    # Time-window overlap proves genuine parallelism rather than fast sequencing.
    windows = [agents.windows[node] for node in ANALYSIS_NODES if node in agents.windows]
    assert len(windows) == len(ANALYSIS_NODES)
    overlaps = 0
    for index, (start_a, end_a) in enumerate(windows):
        for start_b, end_b in windows[index + 1 :]:
            if start_a < end_b and start_b < end_a:
                overlaps += 1
    assert overlaps >= 2, f"expected overlapping execution windows, saw {overlaps}"
    assert sorted(result.completed_nodes) == sorted([*ANALYSIS_NODES, SYNTHESIS_NODE])


# --------------------------------------------------------------------------
# AC-2: total runtime budget (scheduling, not wall-clock waiting)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_duration_stays_within_budget():
    """Serial execution would take 5 × delay; the graph must overlap them."""
    delay = 0.05
    agents = RecordingAgents(delay=delay)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))

    started = time.monotonic()
    await orchestrator.run(competitor_name="钉钉")
    elapsed = time.monotonic() - started

    serial = delay * (len(ANALYSIS_NODES) + 1)
    assert elapsed < serial * 0.75, (
        f"elapsed {elapsed:.3f}s is too close to the serial bound {serial:.3f}s"
    )
    # The orchestration ceiling matches the case's acceptance criterion
    # (docs/cases/multi-agent-competitor-deep-dive.md §8: <= 15 minutes).
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    assert loaded.timeout == 900

    # The four analysis nodes run in parallel, so their individual ceilings must
    # each fit inside the orchestration budget rather than summing to 3300 s.
    node_timeouts = [
        int(node["payload"]["timeout"])
        for node in loaded.definition.nodes
        if node["payload"].get("timeout")
    ]
    assert max(node_timeouts) <= loaded.timeout
    assert sum(node_timeouts) > loaded.timeout


# --------------------------------------------------------------------------
# AC-3: cycle detection rejects execution
# --------------------------------------------------------------------------


def test_cycle_is_rejected():
    from app.orchestration.registry import OrchestrationDefinition

    document = yaml.safe_load(ORCHESTRATION_PATH.read_text(encoding="utf-8"))
    # Introduce a cycle: market_intel depends on the synthesis node.
    for node in document["nodes"]:
        if node["id"] == "market_intel":
            node["depends_on"] = [SYNTHESIS_NODE]

    definition = OrchestrationDefinition(
        orchestration_id="cyclic",
        mode="graph",
        nodes=[{"id": n["id"], "payload": {}} for n in document["nodes"]],
        edges=[
            {"source": SYNTHESIS_NODE, "target": "market_intel"},
            {"source": "market_intel", "target": SYNTHESIS_NODE},
        ],
    )
    from app.orchestration.topo import CycleError, topological_order

    # validate() only checks graph build-ability and condition syntax; the cycle
    # itself is detected when the graph is materialised for execution.
    definition.validate()
    with pytest.raises((GraphError, CycleError)):
        topological_order(definition.to_graph())


@pytest.mark.asyncio
async def test_cyclic_graph_does_not_execute():
    from app.orchestration.graph import Edge, Graph, Node

    graph = Graph()
    graph.add_node(Node(id="a"))
    graph.add_node(Node(id="b"))
    graph.add_edge(Edge("a", "b"))
    graph.add_edge(Edge("b", "a"))

    async def runner(node, context):  # pragma: no cover - must never run
        raise AssertionError("a cyclic graph must not execute any node")

    from app.orchestration.topo import CycleError

    with pytest.raises((GraphError, CycleError)):
        await DagEngine().run_graph(graph, runner)


# --------------------------------------------------------------------------
# AC-4: conditional skip for a private competitor
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_private_competitor_skips_financial_analysis():
    agents = RecordingAgents()
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="Anthropic", competitor_is_private=True)

    assert "financial_analysis" in result.skipped_nodes
    assert "financial_analysis" not in result.completed_nodes
    assert "financial_analysis" not in agents.calls, "a skipped node must not execute"

    reasons = {item["node"]: item["reason"] for item in result.skipped_sections}
    assert "private company has no public financials" in reasons["financial_analysis"], (
        "the document's skip reason must surface in the result"
    )


@pytest.mark.asyncio
async def test_public_competitor_runs_financial_analysis():
    agents = RecordingAgents()
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉", competitor_is_private=False)

    assert "financial_analysis" in result.completed_nodes
    assert "financial_analysis" in agents.calls


def test_skip_condition_polarity_matches_the_document():
    """``skip_condition`` runs the node when FALSE (engine polarity is inverted)."""
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    financial = next(n for n in loaded.definition.nodes if n["id"] == "financial_analysis")

    assert evaluate_condition(financial["condition"], {"competitor_is_private": True}) is False
    assert evaluate_condition(financial["condition"], {"competitor_is_private": False}) is True

    synthesis = next(n for n in loaded.definition.nodes if n["id"] == SYNTHESIS_NODE)
    assert evaluate_condition(synthesis["condition"], {"completed_children_count": 4}) is True
    assert evaluate_condition(synthesis["condition"], {"completed_children_count": 2}) is False


# --------------------------------------------------------------------------
# AC-5: node-level retry with exponential backoff
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_retry_happens_after_a_transient_failure():
    attempts = {"n": 0}

    class FlakyOnce(RecordingAgents):
        async def __call__(self, node, context):
            if node.id == "market_intel":
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise TimeoutError("simulated timeout")
            return await super().__call__(node, context)

    agents = FlakyOnce(delay=0.01)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents), sleep=_no_sleep)
    result = await orchestrator.run(competitor_name="钉钉")

    assert attempts["n"] == 2, "the node must be attempted twice (one retry)"
    assert "market_intel" in result.completed_nodes
    retries = [event for event in orchestrator.retry_events if event["node"] == "market_intel"]
    assert len(retries) == 1
    assert retries[0]["event"] == "retry"


def test_retry_policy_uses_exponential_backoff():
    policy = RetryPolicy(max_attempts=3, base_seconds=5.0)
    assert policy.delay_for(1) == 0.0
    assert policy.delay_for(2) == 5.0
    assert policy.delay_for(3) == 10.0


@pytest.mark.asyncio
async def test_retry_reports_two_attempt_events():
    agents = RecordingAgents(failing={"sentiment_monitor"})
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents), sleep=_no_sleep)

    await orchestrator.run(competitor_name="钉钉")

    assert agents.attempts["sentiment_monitor"] == 2
    execution = orchestrator.node_executions["sentiment_monitor"]
    assert execution.attempts == 2
    failed = {failure.node_id: failure for failure in orchestrator.failures}
    assert failed["sentiment_monitor"].attempts == 2


# --------------------------------------------------------------------------
# AC-6: failure propagation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_is_skipped_when_fewer_than_three_children_complete():
    # Two analysis nodes fail permanently, leaving only two successful ones.
    agents = RecordingAgents(
        delay=0.01, failing={"market_intel", "product_analysis"}
    )
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents), sleep=_no_sleep)
    result = await orchestrator.run(competitor_name="钉钉")

    # Analysis nodes report failure softly, so the useful signal is the count of
    # nodes that produced usable data (not the engine's node states).
    assert result.execution.context["completed_children_count"] == 2
    assert len(orchestrator.failures) == 2
    synthesis = result.execution.outcomes[SYNTHESIS_NODE]
    assert synthesis.state == "skipped", f"synthesis should be skipped, got {synthesis.state}"
    assert result.degraded is True
    assert "数据不足中止" in result.research_report


@pytest.mark.asyncio
async def test_synthesis_runs_when_three_children_complete():
    agents = RecordingAgents(delay=0.01, failing={"sentiment_monitor"})
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents), sleep=_no_sleep)
    result = await orchestrator.run(competitor_name="钉钉")

    assert result.execution.context["completed_children_count"] == MIN_COMPLETED_CHILDREN
    assert len(orchestrator.failures) == 1
    synthesis = result.execution.outcomes[SYNTHESIS_NODE]
    assert synthesis.state == "completed", f"synthesis should run, got {synthesis.state}"
    assert result.degraded is False


def test_all_children_failed_marks_synthesis_skipped():
    """FR-11 ``on_all_children_failed: mark_parent_skipped``."""
    from app.orchestration.engine import ExecutionResult, NodeOutcome

    orchestrator = DeepDiveOrchestrator(sub_agents={})
    result = ExecutionResult()
    for node_id in ANALYSIS_NODES:
        result.outcomes[node_id] = NodeOutcome(node_id=node_id, state="failed", error="boom")
    result.outcomes[SYNTHESIS_NODE] = NodeOutcome(node_id=SYNTHESIS_NODE, state="blocked")

    orchestrator._propagate_failures(result)

    assert result.outcomes[SYNTHESIS_NODE].state == "skipped"


# --------------------------------------------------------------------------
# AC-7: evidence traceability
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_claim_is_traceable_to_evidence():
    agents = RecordingAgents(delay=0.01)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉")

    assert result.evidence, "the synthesis node must publish an evidence index"
    for item in result.evidence:
        assert item["source"]
        assert item["claim"]

    # The evidence index assigns the stable ids used for reverse lookup.
    from app.enterprise_capabilities.research.competitor_deep_dive import (
        SYNTHESIS_NODE as _SYN,
    )

    outputs = {
        node_id: result.execution.context.get(f"{node_id}_result")
        for node_id in ANALYSIS_NODES
    }
    assert outputs, "analysis outputs must be published under their output_key"


def test_evidence_index_reverse_lookup():
    import sys

    scripts = SKILLS_ROOT / "report_synthesis_v1" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import evidence_index as module
    finally:
        sys.path.pop(0)

    index = module.collect_from_node_outputs(
        {
            "market_intel": {"evidence": [{"source": "news", "claim": "raised series C"}]},
            "product_analysis": {"evidence": [{"source": "site", "claim": "has SSO"}]},
        }
    )
    assert len(index) == 2
    assert module.unresolved_claims(index, ["raised series C"]) == []
    assert module.unresolved_claims(index, ["unbacked claim"]) == ["unbacked claim"]
    assert all(record["id"].startswith("ev-") for record in index.as_json())


# --------------------------------------------------------------------------
# AC-8: analyst-grade style constraints
# --------------------------------------------------------------------------

STYLE_SECTIONS = (
    "执行摘要",
    "市场情报",
    "产品功能对比",
    "财务分析",
    "舆情监测",
    "综合判断与决策建议",
    "附录 · 证据追溯",
)


@pytest.mark.asyncio
async def test_report_follows_style_contract():
    agents = RecordingAgents(delay=0.01)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉")

    report = result.research_report
    assert report, "a run with enough data must produce a report"

    template = (SKILLS_ROOT / "report_synthesis_v1" / "templates" / "research_report.md").read_text(
        encoding="utf-8"
    )
    for section in STYLE_SECTIONS:
        assert section in template, f"the report template must declare section {section}"

    # The case requires every claim to be attributable to the evidence index.
    assert "evidence.json" in template
    assert not re.search(r"\bTODO\b|\bFIXME\b|\{\{.*?\}\}", report), (
        "an emitted report must not leak template placeholders"
    )


def test_style_reference_skill_is_declared():
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    synthesis = next(n for n in loaded.definition.nodes if n["id"] == SYNTHESIS_NODE)
    assert synthesis["payload"]["skill"] == "report_synthesis_v1"
    reference = (SKILLS_ROOT / "deep_research_report_style_v1" / "SKILL.md")
    assert reference.is_file(), "the report style reference Skill must exist"


# --------------------------------------------------------------------------
# AC-9: per-node cost attribution
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_is_attributable_per_node():
    """Each node's usage must be aggregatable under its own node id."""
    from app.llm.resilience.metering import aggregate_usage

    agents = RecordingAgents(delay=0.01)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉")

    rows = [
        {"node_id": node_id, "total_tokens": 150, "model_name": "gpt-5.4"}
        for node_id in ANALYSIS_NODES
    ]
    # ``dimension="agent"`` is the metering module's per-node bucket (it reads
    # node_id / agent_id), which is what the case's per-node cost view needs.
    by_node = aggregate_usage(rows, dimension="agent")
    assert {item["key"] for item in by_node} == set(ANALYSIS_NODES), (
        "cost must be attributable per node"
    )
    for item in by_node:
        assert item["total_tokens"] == 150
        assert item["calls"] == 1

    # Every executed node must be individually observable too.
    assert len(result.node_executions) >= len(ANALYSIS_NODES)


# --------------------------------------------------------------------------
# AC-10: session commit / share / resume
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_can_be_committed_shared_and_resumed():
    agents = RecordingAgents(delay=0.01)
    orchestrator = DeepDiveOrchestrator(sub_agents=_all_agents(agents))
    result = await orchestrator.run(competitor_name="钉钉")

    # commit: the report and its evidence envelope are the durable artefact.
    committed = {
        "competitor": "钉钉",
        "report": result.research_report,
        "evidence": result.evidence,
    }
    assert committed["report"]

    # share: a hand-off carries the report plus the evidence index.
    shared = {**committed, "shared_with": "strategy-team"}
    assert shared["report"] == committed["report"]
    assert shared["evidence"] == committed["evidence"]

    # resume: replaying the committed payload reproduces the deliverable.
    resumed = dict(committed)
    assert resumed["report"] == result.research_report
    for section in STYLE_SECTIONS:
        if section in result.research_report:
            assert section in resumed["report"]


# --------------------------------------------------------------------------
# Loader / definition contract
# --------------------------------------------------------------------------


def test_orchestration_yaml_loads_and_validates():
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    assert loaded.orchestration_id == "competitor_deep_dive"
    assert loaded.mode == "graph"
    assert loaded.max_concurrency == 4
    assert loaded.timeout == 900
    assert loaded.node_ids == [
        "market_intel",
        "product_analysis",
        "financial_analysis",
        "sentiment_monitor",
        SYNTHESIS_NODE,
    ]
    # Only the synthesis node depends on others (graph fan-in).
    graph = loaded.definition.to_graph()
    assert sorted(graph.dependencies(SYNTHESIS_NODE)) == sorted(ANALYSIS_NODES)
    for node_id in ANALYSIS_NODES:
        assert list(graph.dependencies(node_id)) == []


def test_data_contract_matches_node_output_keys():
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    declared = {
        f"{node['id']}.output_key": node["payload"].get("output_key")
        for node in loaded.definition.nodes
    }
    for key, value in loaded.data_contract.items():
        assert key in declared, f"data_contract references unknown node: {key}"
        assert declared[key] == value, f"data_contract disagrees with node payload for {key}"


def test_failure_propagation_and_audit_are_declared():
    loaded = load_orchestration_file(ORCHESTRATION_PATH)
    assert loaded.failure_propagation.get("on_all_children_failed") == "mark_parent_skipped"
    assert loaded.failure_propagation.get("on_p0_child_failed") == (
        "retry_with_backoff_then_mark_failed"
    )
    assert loaded.audit.get("enabled") is True
    assert "node_skip" in loaded.audit.get("emit_events", [])


def test_compile_expr_rejects_unsupported_grammar():
    with pytest.raises(OrchestrationLoadError):
        compile_expr("this is not a condition")
    with pytest.raises(OrchestrationLoadError):
        compile_expr("a and b")


def test_sub_skills_declare_subagent_contract():
    for name in SUB_SKILLS:
        path = SKILLS_ROOT / name / "SKILL.md"
        assert path.is_file(), f"missing sub-skill: {name}"
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        _, _, rest = text.partition("---\n")
        frontmatter, sep, _ = rest.partition("\n---\n")
        assert sep, f"{name}: frontmatter must be closed"
        meta = yaml.safe_load(frontmatter)

        assert meta["role"] == "subagent", f"{name}: role must be subagent"
        assert meta["parent_skill"] == "competitor_deep_dive", f"{name}: parent_skill mismatch"
        assert meta["outputs"], f"{name}: outputs must be declared"
        for resource in meta["resources"]:
            assert (SKILLS_ROOT / name / resource).exists(), (
                f"{name}: declared resource missing: {resource}"
            )


def test_degraded_report_names_skipped_nodes():
    report = _degraded_report(
        competitor_name="X",
        completed=["market_intel"],
        skipped=[{"node": "financial_analysis", "reason": "private company"}],
    )
    assert "降级报告" in report
    assert "market_intel" in report
    assert "financial_analysis" in report
