"""035 US1 (T018): the cost-attribution dimensions are captured on the record.

``TokenUsageRecord`` gained ``agent_id`` / ``skill_id`` / ``workspace_id``; the
``InstrumentedLLMClient`` reads them from the resolved ``output_spec`` (which
merges the request context) and the capability runtime seeds them per execution.
These tests pin the data-source contract so the dashboard can bucket by agent /
space without guessing.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from app.llm.instrumented_client import InstrumentedLLMClient
from app.llm.types import LLMResponse, Message, Role
from app.enterprise_capabilities.runtime.service import _split_capability_ref


class _FakeInner:
    """Minimal inner client: returns a fixed response and records no usage."""

    def __init__(self, usage: dict[str, int] | None = None) -> None:
        self._usage = usage or {}

    async def ainvoke(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(message=Message(role=Role.ASSISTANT, content="ok"), usage=self._usage)

    async def astream(self, messages, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        yield LLMResponse(message=Message(role=Role.ASSISTANT, content="ok"), usage=self._usage)

    async def ainvoke_structured(self, messages, schema, **kwargs):
        return schema()

    def consume_invocation_record(self) -> dict[str, Any] | None:
        return {}


def _client(inner, *, model_name: str = "gpt-5.2", model_id: str = "m1", **output_spec) -> InstrumentedLLMClient:
    return InstrumentedLLMClient(
        inner,
        model_name=model_name,
        model_id=model_id,
        output_spec=output_spec,
    )


def test_submit_record_captures_attribution_dimensions(monkeypatch) -> None:
    import asyncio

    from app.infrastructure import runtime_services

    captured: list[Any] = []
    monkeypatch.setattr(
        runtime_services.token_usage_dispatcher,
        "submit",
        lambda record: (captured.append(record), True)[1],
    )

    client = _client(
        _FakeInner(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
        agent_id="research.progressive",
        skill_id="v1",
        workspace_id="ws-42",
        tenant_id="m-1",
        user_id="u-7",
    )
    asyncio.run(client.ainvoke([Message(role=Role.USER, content="hi")]))

    assert len(captured) == 1
    record = captured[0]
    assert record.agent_id == "research.progressive"
    assert record.skill_id == "v1"
    assert record.workspace_id == "ws-42"


def test_submit_record_space_falls_back_to_project_id(monkeypatch) -> None:
    import asyncio

    from app.infrastructure import runtime_services

    captured: list[Any] = []
    monkeypatch.setattr(
        runtime_services.token_usage_dispatcher,
        "submit",
        lambda record: (captured.append(record), True)[1],
    )

    client = _client(
        _FakeInner(usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
        project_id="proj-9",
    )
    asyncio.run(client.ainvoke([Message(role=Role.USER, content="hi")]))

    assert captured[0].workspace_id == "proj-9"
    # no agent / skill source -> empty, never a fabricated value.
    assert captured[0].agent_id == ""
    assert captured[0].skill_id == ""


def test_resolved_output_spec_merges_request_context() -> None:
    from app.infrastructure.request_context import reset_request_context, set_request_context

    previous = set_request_context({"agent_id": "ctx-agent", "workspace_id": "ctx-space"})
    try:
        client = _client(_FakeInner())
        resolved = client._resolved_output_spec()
        assert resolved.get("agent_id") == "ctx-agent"
        assert resolved.get("workspace_id") == "ctx-space"
    finally:
        reset_request_context(previous)


def test_split_capability_ref_maps_agent_and_skill() -> None:
    assert _split_capability_ref("research.progressive@v1") == ("research.progressive", "v1")
    assert _split_capability_ref("knowledge.search@v1") == ("knowledge.search", "v1")
    # a ref without a version tag names the agent and leaves the skill empty.
    assert _split_capability_ref("plain.agent") == ("plain.agent", "")
    assert _split_capability_ref("") == ("", "")
    assert _split_capability_ref("   ") == ("", "")