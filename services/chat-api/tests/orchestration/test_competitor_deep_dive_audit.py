"""FR-7 audit wiring + FR-8 persisted definition for 010."""

from __future__ import annotations
import pytest

import asyncio

from app.enterprise_capabilities.research.competitor_deep_dive import (
    ANALYSIS_NODES,
    SYNTHESIS_NODE,
    DeepDiveOrchestrator,
)
from app.orchestration.store import load_orchestration_persisted
from app.enterprise_capabilities.research.competitor_deep_dive import ORCHESTRATION_PATH


class _StubAgent:
    async def __call__(self, node, context):
        return {
            "node": node.id,
            "markdown": f"# section from {node.id}",
            "evidence": [{"source": node.id, "claim": f"claim-{node.id}"}],
        }


def _all_agents() -> dict[str, _StubAgent]:
    agent = _StubAgent()
    return {node_id: agent for node_id in (*ANALYSIS_NODES, SYNTHESIS_NODE)}


class MemorySink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, event: str, feature: str, document: dict) -> None:
        self.events.append((event, feature, document))


async def _no_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_run_emits_audit_events():
    sink = MemorySink()
    orch = DeepDiveOrchestrator(
        sub_agents=_all_agents(),
        sleep=_no_sleep,
        audit_sink=sink,
        tenant_id="t1",
        actor="u1",
    )
    await orch.run(competitor_name="Acme")
    event_names = [e[0] for e in sink.events]
    assert "dag.run_started" in event_names
    assert "dag.run_finished" in event_names
    assert event_names.count("dag.node_start") >= 5
    assert all(e[1] == "010" for e in sink.events)
    assert all(e[2].get("tenant_id") == "t1" for e in sink.events)
    assert all(e[2].get("actor") == "u1" for e in sink.events)


@pytest.mark.asyncio
async def test_persisted_store_registers_yaml():
    loaded = await load_orchestration_persisted("competitor_deep_dive", yaml_path=ORCHESTRATION_PATH)
    assert loaded.orchestration_id == "competitor_deep_dive"
