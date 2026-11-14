"""005 wiring: ResearchFocusBuilder drives the run + FR-10 audit events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.knowledge.research_focus_builder import ResearchFocusBuilder
from app.enterprise_capabilities.research.progressive.agent import ProgressiveResearchAgent


class _FakeProviderRouter:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def search(self, queries, *, max_results_per_query):
        self.calls.append(list(queries))
        return [], []


def _make_modes_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "modes.yaml"
    cfg.write_text(
        "modes:\n"
        "  report:\n"
        "    query_templates:\n"
        "      - \"行业报告模板: {topic}\"\n"
        "    source_priority: [internal, web]\n"
        "    evidence_schema: [source, date]\n",
        encoding="utf-8",
    )
    return cfg


@pytest.mark.asyncio
async def test_focus_builder_seeds_initial_queries(tmp_path, monkeypatch):
    cfg = _make_modes_cfg(tmp_path)
    builder = ResearchFocusBuilder(config_path=cfg)

    class _FakeLLM:
        async def __call__(self, *a, **k):
            raise AssertionError("LLM must not be called for planning")

    audit: list[tuple[str, str, dict]] = []
    router = _FakeProviderRouter()
    agent = ProgressiveResearchAgent(
        provider_router=router,
        llm=_FakeLLM(),
        research_focus_builder=builder,
        selected_mode="report",
        evidence_mode="standard",
        audit_sink=lambda feature, event, doc, **kw: audit.append((feature, event, {**doc, **kw})),
        tenant_id="t1",
        actor="u1",
    )

    # _plan_initial_queries will call the LLM and raise; we test the focus seeding
    # path by stubbing the planner to return nothing so templates become the seed.
    async def _no_plan(self, query, *, language):
        return []

    monkeypatch.setattr(ProgressiveResearchAgent, "_plan_initial_queries", _no_plan)

    result = await agent.run(query="新能源市场", language="zh")
    # Templates from the focus config must have seeded the first round.
    assert any("行业报告模板" in q for q in router.calls[0]), router.calls
    # FR-10 audit must have been emitted (start + finish).
    events = {e for _, e, _ in audit}
    assert "research.run_started" in events
    assert "research.run_finished" in events
    # tenant/actor propagated.
    assert audit[0][2]["tenant_id"] == "t1"
