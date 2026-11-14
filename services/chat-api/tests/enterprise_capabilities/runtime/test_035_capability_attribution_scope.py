"""035 T017: capability-level cost-attribution dimensions must survive inner adapters.

``InternalCapabilityService.execute`` seeds ``agent_id`` / ``skill_id`` (and
``tenant_id`` / ``user_id`` / ``configured_model``) into the request context for the
whole capability execution. The runtime adapters (``external_search``,
``progressive_research``) must MERGE their own turn-scope keys instead of SET, so the
outer dimensions are not wiped out and every LLM call the adapter makes is attributed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.enterprise_capabilities.runtime import adapters
from app.enterprise_capabilities.runtime.contracts import CapabilityExecutionContext
from app.enterprise_capabilities.runtime.registry import CapabilityHandlerRegistry
from app.enterprise_capabilities.runtime.service import (
    InternalCapabilityService,
    _split_capability_ref,
)
from app.infrastructure.request_context import get_request_context, set_request_context


def _context(**overrides: Any) -> CapabilityExecutionContext:
    base: dict[str, Any] = {
        "tenant_id": "t1",
        "user_id": "u1",
        "conversation_id": "c1",
        "kernel_session_id": "k1",
        "profile_version": "pv1",
        "action_id": "act-1",
    }
    base.update(overrides)
    return CapabilityExecutionContext(**base)


class TestSplitCapabilityRef:
    def test_agent_and_skill(self) -> None:
        assert _split_capability_ref("research.progressive@v1") == ("research.progressive", "v1")

    def test_no_at_version(self) -> None:
        assert _split_capability_ref("search") == ("search", "")

    def test_empty_and_blank(self) -> None:
        assert _split_capability_ref("") == ("", "")
        assert _split_capability_ref(None) == ("", "")

    def test_strips_spaces(self) -> None:
        assert _split_capability_ref("  a.b@v2 ") == ("a.b", "v2")


class TestCapabilityServiceSeedsDimensions:
    async def test_handler_sees_agent_and_skill(self) -> None:
        seen: dict[str, Any] = {}

        async def handler(args: dict[str, Any], ctx: CapabilityExecutionContext) -> dict[str, Any]:
            seen["ctx"] = get_request_context()
            return {"success": True}

        registry = CapabilityHandlerRegistry()
        registry.register("search@v1", handler)
        service = InternalCapabilityService(registry)

        result = await service.execute("search@v1", {}, _context())
        assert result == {"success": True}
        assert seen["ctx"]["agent_id"] == "search"
        assert seen["ctx"]["skill_id"] == "v1"
        assert seen["ctx"]["tenant_id"] == "t1"
        assert seen["ctx"]["user_id"] == "u1"
        assert get_request_context() == {}


class TestAdaptersMergeTurnScope:
    async def test_external_search_preserves_capability_dims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        async def fake_search(*args: Any, **kwargs: Any) -> tuple[list[Any], Any]:
            seen["ctx"] = get_request_context()
            return [], {"providers": []}

        monkeypatch.setattr(adapters.ProviderRouter, "search", fake_search)

        previous = set_request_context({"agent_id": "search", "skill_id": "v1"})
        try:
            await adapters.external_search({"queries": ["hello"]}, _context())
        finally:
            # restore happens inside adapters; reset our own seed
            pass
        # adapters' reset returns the outer seed, so agent/skill survive
        assert seen["ctx"]["agent_id"] == "search"
        assert seen["ctx"]["skill_id"] == "v1"
        assert seen["ctx"]["tenant_id"] == "t1"
        assert seen["ctx"]["user_id"] == "u1"
        set_request_context(previous)

    async def test_progressive_research_preserves_capability_dims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        # model_config present so we get past the unavailable branch
        async def _fake_get_model_config(model_id: str, tenant_id: str) -> dict[str, Any]:
            return {"model": "m"}

        async def _fake_get_default_model_config(tenant_id: str) -> dict[str, Any]:
            return {"model": "m"}

        monkeypatch.setattr(adapters, "get_model_config", _fake_get_model_config)
        monkeypatch.setattr(adapters, "get_default_model_config", _fake_get_default_model_config)
        monkeypatch.setattr(adapters, "build_research_evidence_bundle", lambda **kw: None)
        monkeypatch.setattr(
            adapters, "build_document_evidence_bundle", lambda **kw: None
        )

        class _Result:
            ok = True
            query = "q"
            results: list[Any] = []
            evidence_sufficient = True
            budget_exhausted = False
            stop_reason = "max_rounds"

            def model_dump(self, mode: str = "json") -> dict[str, Any]:
                return {"ok": self.ok, "query": self.query, "results": self.results,
                        "evidence_sufficient": self.evidence_sufficient,
                        "budget_exhausted": self.budget_exhausted,
                        "stop_reason": self.stop_reason}

        class _Agent:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._calls = 0

            async def run(self, **kwargs: Any) -> _Result:
                self._calls += 1
                seen["ctx"] = get_request_context()
                return _Result()

        monkeypatch.setattr(adapters, "ProgressiveResearchAgent", _Agent)

        previous = set_request_context({"agent_id": "research.progressive", "skill_id": "v1"})
        try:
            await adapters.progressive_research({"query": "q"}, _context())
        finally:
            pass
        assert seen["ctx"]["agent_id"] == "research.progressive"
        assert seen["ctx"]["skill_id"] == "v1"
        set_request_context(previous)