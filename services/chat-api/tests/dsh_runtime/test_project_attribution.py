"""T014 (FR-005/006): 模型网关调用产生的 token_usage_logs 行必须携带 project_id / user_id。

构造一次完整的 ModelGatewayService.generate() 调用（走 _configured_client 路径），
断言 InstrumentedLLMClient 提交的记录中 project_id 和 user_id 非空；
未绑定会话（无 kernel binding）落 "default"。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, patch

from app.dsh_runtime.model_gateway.project_id import ProjectIdResolver
from app.dsh_runtime.model_gateway.service import ModelGatewayRequest, ModelGatewayService
from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService
from app.llm.types import LLMResponse, Message, Role


def _make_request(session_id: str = "dsh-attr-test") -> ModelGatewayRequest:
    return ModelGatewayRequest(
        profileVersion="profile-a",
        modelInstanceId="model-a",
        provider="askai-model-gateway",
        model="test-model",
        sessionId=session_id,
        messages=[{"role": "user", "content": "hello"}],
    )


def _make_claims() -> "ModelGatewayClaims":
    tokens = ModelGatewayTokenService("attr-test-secret")
    return tokens.verify(
        tokens.issue(
            tenant_id="tenant-a",
            user_id="user-a",
            profile_version="profile-a",
            model_instance_id="model-a",
        )
    )


class _FakeBindings:
    def __init__(self, source_workspace_id: str | None = "proj-attr") -> None:
        self._doc: dict | None = None
        if source_workspace_id is not None:
            self._doc = {"source_workspace_id": source_workspace_id}

    async def by_kernel_session(
        self, kernel_session_id: str, *, tenant_id: str, user_id: str
    ) -> dict | None:
        return self._doc


class _FakeInner:
    async def ainvoke(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(
            message=Message(role=Role.ASSISTANT, content="done"),
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    async def astream(self, messages, **kwargs) -> AsyncGenerator[LLMResponse, None]:
        yield LLMResponse(
            message=Message(role=Role.ASSISTANT, content="done"),
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    async def ainvoke_structured(self, messages, schema, **kwargs):
        return schema()

    def consume_invocation_record(self) -> dict[str, Any] | None:
        return {}


def test_gateway_call_records_project_id_and_user_id(monkeypatch) -> None:
    """绑定存在的会话：token_usage_logs 行的 project_id 和 user_id 非空。"""
    asyncio.run(_test_records_project_and_user(monkeypatch))


async def _test_records_project_and_user(monkeypatch) -> None:
    captured: list[Any] = []
    monkeypatch.setattr(
        "app.infrastructure.runtime_services.token_usage_dispatcher.submit",
        lambda record: (captured.append(record), True)[1],
    )

    bindings = _FakeBindings("proj-attr")
    resolver = ProjectIdResolver(bindings)

    with patch(
        "app.dsh_runtime.model_gateway.service.get_llm_client_by_model_id",
    ) as mock_factory:
        from app.llm.instrumented_client import InstrumentedLLMClient

        async def create_client(model_instance_id, **kwargs):
            output_spec = kwargs.get("output_spec", {})
            return InstrumentedLLMClient(
                _FakeInner(),
                model_name="test-model",
                model_id=model_instance_id,
                output_spec=output_spec,
            )

        mock_factory.side_effect = create_client

        service = ModelGatewayService(project_resolver=resolver)
        response = await service.generate(_make_request(), _make_claims())
        assert response.text == "done"

    assert len(captured) == 1
    record = captured[0]
    assert record.user_id == "user-a", f"user_id missing: {record}"
    assert record.project_id == "proj-attr", f"project_id wrong: {record}"


def test_gateway_call_unbound_session_records_default_project(monkeypatch) -> None:
    """未绑定会话（无 kernel binding）：project_id 落 "default"。"""
    asyncio.run(_test_unbound_default(monkeypatch))


async def _test_unbound_default(monkeypatch) -> None:
    captured: list[Any] = []
    monkeypatch.setattr(
        "app.infrastructure.runtime_services.token_usage_dispatcher.submit",
        lambda record: (captured.append(record), True)[1],
    )

    bindings = _FakeBindings(None)  # 无绑定
    resolver = ProjectIdResolver(bindings)

    with patch(
        "app.dsh_runtime.model_gateway.service.get_llm_client_by_model_id",
    ) as mock_factory:
        from app.llm.instrumented_client import InstrumentedLLMClient

        async def create_client(model_instance_id, **kwargs):
            output_spec = kwargs.get("output_spec", {})
            return InstrumentedLLMClient(
                _FakeInner(),
                model_name="test-model",
                model_id=model_instance_id,
                output_spec=output_spec,
            )

        mock_factory.side_effect = create_client

        service = ModelGatewayService(project_resolver=resolver)
        response = await service.generate(_make_request(), _make_claims())
        assert response.text == "done"

    assert len(captured) == 1
    record = captured[0]
    assert record.user_id == "user-a"
    assert record.project_id == "default", f"unbound session should record 'default': {record}"
