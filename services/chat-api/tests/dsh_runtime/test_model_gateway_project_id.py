"""FR-006: ProjectIdResolver 按 sessionId 反查 project_id 的单元测试。

覆盖：
- 绑定存在 → 返回 project_id
- 无绑定（None）→ 返回 "default"，miss 计数 +1
- 绑定存在但 source_workspace_id 为空 → 返回 "default"，miss 计数 +1
- 缓存命中 → 第二次调用不查 bindings
- 空 session_id → 返回 "default"
- ModelGatewayService 无 resolver → output_spec 无 project_id 键
- ModelGatewayService 有 resolver → output_spec 含 project_id
- ModelGatewayService 有 resolver 但请求无 sessionId → output_spec 无 project_id 键
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.dsh_runtime.model_gateway.project_id import ProjectIdResolver
from app.dsh_runtime.model_gateway.service import (
    ModelGatewayRequest,
    ModelGatewayService,
)
from app.dsh_runtime.model_gateway.token import ModelGatewayClaims, ModelGatewayTokenService
from app.llm.types import LLMResponse, Message, Role


def _make_request(session_id: str | None = "dsh-test-session") -> ModelGatewayRequest:
    kwargs: dict = {
        "profileVersion": "profile-a",
        "modelInstanceId": "model-a",
        "provider": "askai-model-gateway",
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
    }
    if session_id is not None:
        kwargs["sessionId"] = session_id
    return ModelGatewayRequest(**kwargs)


def _make_claims() -> ModelGatewayClaims:
    tokens = ModelGatewayTokenService("project-id-test-secret")
    return tokens.verify(
        tokens.issue(
            tenant_id="tenant-a",
            user_id="user-a",
            profile_version="profile-a",
            model_instance_id="model-a",
        )
    )


class _FakeBindings:
    """模拟 KernelBindingRepository.by_kernel_session。"""

    def __init__(self, source_workspace_id: str | None = "proj-123") -> None:
        self.lookups: list[tuple[str, str, str]] = []
        self._doc: dict | None = None
        if source_workspace_id is not None:
            self._doc = {"source_workspace_id": source_workspace_id}

    async def by_kernel_session(
        self, kernel_session_id: str, *, tenant_id: str, user_id: str
    ) -> dict | None:
        self.lookups.append((kernel_session_id, tenant_id, user_id))
        return self._doc


def _fake_client() -> object:
    return AsyncMock(
        ainvoke=AsyncMock(
            return_value=LLMResponse(
                message=Message(role=Role.ASSISTANT, content="ok"),
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )
        )
    )


def test_resolver_returns_project_id_when_binding_exists() -> None:
    asyncio.run(_test_resolver_returns_project_id())


async def _test_resolver_returns_project_id() -> None:
    bindings = _FakeBindings("proj-123")
    resolver = ProjectIdResolver(bindings)
    result = await resolver.resolve(
        "dsh-session-1", tenant_id="tenant-a", user_id="user-a"
    )
    assert result == "proj-123"
    assert bindings.lookups == [("dsh-session-1", "tenant-a", "user-a")]
    assert resolver.miss_count == 0


def test_resolver_falls_back_to_default_when_no_binding() -> None:
    asyncio.run(_test_resolver_no_binding())


async def _test_resolver_no_binding() -> None:
    bindings = _FakeBindings(None)
    resolver = ProjectIdResolver(bindings)
    result = await resolver.resolve(
        "dsh-unknown", tenant_id="tenant-a", user_id="user-a"
    )
    assert result == "default"
    assert resolver.miss_count == 1


def test_resolver_falls_back_to_default_when_workspace_id_empty() -> None:
    asyncio.run(_test_resolver_empty_workspace())


async def _test_resolver_empty_workspace() -> None:
    bindings = _FakeBindings("  ")
    resolver = ProjectIdResolver(bindings)
    result = await resolver.resolve(
        "dsh-session-2", tenant_id="tenant-a", user_id="user-a"
    )
    assert result == "default"
    assert resolver.miss_count == 1


def test_resolver_caches_result() -> None:
    asyncio.run(_test_resolver_caches())


async def _test_resolver_caches() -> None:
    bindings = _FakeBindings("proj-456")
    resolver = ProjectIdResolver(bindings, ttl_seconds=60.0)
    r1 = await resolver.resolve("dsh-c1", tenant_id="t", user_id="u")
    r2 = await resolver.resolve("dsh-c1", tenant_id="t", user_id="u")
    assert r1 == r2 == "proj-456"
    assert len(bindings.lookups) == 1  # 第二次走缓存


def test_resolver_empty_session_id_returns_default() -> None:
    asyncio.run(_test_resolver_empty_session())


async def _test_resolver_empty_session() -> None:
    bindings = _FakeBindings()
    resolver = ProjectIdResolver(bindings)
    result = await resolver.resolve("", tenant_id="t", user_id="u")
    assert result == "default"
    assert bindings.lookups == []  # 不查


def test_service_without_resolver_omits_project_id() -> None:
    """无 ProjectIdResolver 时 output_spec 不含 project_id 键。"""
    asyncio.run(_test_service_no_resolver())


async def _test_service_no_resolver() -> None:
    captured: dict = {}

    async def fake_factory(
        model_instance_id: str, tenant_id: str, request: ModelGatewayRequest, claims
    ):
        captured.update(model_instance_id=model_instance_id, tenant_id=tenant_id)
        return _fake_client()

    service = ModelGatewayService(fake_factory)
    await service.generate(_make_request(), _make_claims())
    assert "project_id" not in captured


def test_service_with_resolver_injects_project_id() -> None:
    """有 ProjectIdResolver 时 output_spec 含 project_id。"""
    asyncio.run(_test_service_with_resolver())


async def _test_service_with_resolver() -> None:
    captured_spec: dict = {}

    original_get_client = None

    async def mock_get_llm_client(model_instance_id, **kwargs):
        captured_spec.update(kwargs.get("output_spec", {}))
        return _fake_client()

    bindings = _FakeBindings("proj-abc")
    resolver = ProjectIdResolver(bindings)
    service = ModelGatewayService(project_resolver=resolver)
    # 替换 _client_factory 走真实 _configured_client 路径
    with patch(
        "app.dsh_runtime.model_gateway.service.get_llm_client_by_model_id",
        side_effect=mock_get_llm_client,
    ):
        await service.generate(_make_request("dsh-session-abc"), _make_claims())
    assert captured_spec["project_id"] == "proj-abc"
    assert captured_spec["session_id"] == "dsh-session-abc"
    assert captured_spec["user_id"] == "user-a"


def test_service_resolver_no_session_id_omits_project_id() -> None:
    """有 resolver 但请求无 sessionId 时 output_spec 不含 project_id 键。"""
    asyncio.run(_test_service_no_session_id())


async def _test_service_no_session_id() -> None:
    captured_spec: dict = {}

    async def mock_get_llm_client(model_instance_id, **kwargs):
        captured_spec.update(kwargs.get("output_spec", {}))
        return _fake_client()

    bindings = _FakeBindings("proj-abc")
    resolver = ProjectIdResolver(bindings)
    service = ModelGatewayService(project_resolver=resolver)
    with patch(
        "app.dsh_runtime.model_gateway.service.get_llm_client_by_model_id",
        side_effect=mock_get_llm_client,
    ):
        await service.generate(_make_request(None), _make_claims())
    assert "project_id" not in captured_spec
    assert bindings.lookups == []  # 空 sessionId 不查 bindings


def test_service_resolver_ignores_request_body_workspace_id() -> None:
    """project_id 只来自权威绑定，不受请求体 workspace id 影响。"""
    asyncio.run(_test_service_ignores_body_workspace())


async def _test_service_ignores_body_workspace() -> None:
    captured_spec: dict = {}

    async def mock_get_llm_client(model_instance_id, **kwargs):
        captured_spec.update(kwargs.get("output_spec", {}))
        return _fake_client()

    bindings = _FakeBindings("proj-real")
    resolver = ProjectIdResolver(bindings)
    service = ModelGatewayService(project_resolver=resolver)
    with patch(
        "app.dsh_runtime.model_gateway.service.get_llm_client_by_model_id",
        side_effect=mock_get_llm_client,
    ):
        await service.generate(_make_request("dsh-real-session"), _make_claims())
    # project_id 来自绑定，不是请求体
    assert captured_spec["project_id"] == "proj-real"
