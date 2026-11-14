"""023 T082 — LLM 通道级资源池隔离。

断言三件事：
1. 每个 provider 有**自己的**连接池句柄（不共用 openai SDK 隐式池）；
2. 同一 provider 重复构造客户端时复用句柄，且不触发「重复注册」拒绝；
3. 上限/keepalive 由 env 驱动，且 keepalive 不会超过总上限。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.common.dependency_guard import PoolRegistry
from app.llm.providers import pools


def _fresh_registry() -> PoolRegistry:
    return PoolRegistry()


@pytest.fixture(autouse=True)
def _clean_pools():
    pools.reset_provider_pools()
    yield
    pools.reset_provider_pools()


def _transport_max_connections(client) -> int | None:
    """httpx 0.28 没有公开的 limits 读取口，只能从 transport 的 pool 上取。"""
    transport = getattr(client, "_transport", None)
    pool_obj = getattr(transport, "_pool", None)
    value = getattr(pool_obj, "_max_connections", None)
    return int(value) if value is not None else None


def test_each_provider_has_its_own_pool_handle():
    azure = pools.provider_http_client(pools.PROVIDER_AZURE_OPENAI)
    default = pools.provider_http_client(pools.PROVIDER_DEFAULT_OPENAI)
    qwen = pools.provider_http_client(pools.PROVIDER_QWEN)

    assert len({id(azure), id(default), id(qwen)}) == 3
    assert pools.default_pool_registry.shared_handle_count() == {}
    for provider in (
        pools.PROVIDER_AZURE_OPENAI,
        pools.PROVIDER_DEFAULT_OPENAI,
        pools.PROVIDER_QWEN,
    ):
        spec = pools.provider_pool_spec(provider)
        assert spec is not None, f"{provider} 未登记"
        assert spec.dependency == f"llm:{provider}"
        assert spec.max_connections >= 1


def test_same_provider_reuses_handle_without_duplicate_registration():
    first = pools.provider_http_client(pools.PROVIDER_DEFAULT_OPENAI)
    second = pools.provider_http_client(pools.PROVIDER_DEFAULT_OPENAI)

    assert first is second
    # 重复构造不抛 ValueError（register 的重复保护被「更新语义」包住）
    spec = pools.provider_pool_spec(pools.PROVIDER_DEFAULT_OPENAI)
    assert spec is not None and spec.pool is first


def test_provider_limit_comes_from_env(monkeypatch):
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_MAX_CONNECTIONS", "7")
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_MAX_KEEPALIVE_CONNECTIONS", "3")

    client = pools.provider_http_client(pools.PROVIDER_QWEN)

    assert pools.provider_max_connections(pools.PROVIDER_QWEN) == 7
    assert pools.provider_max_keepalive(pools.PROVIDER_QWEN) == 3
    assert _transport_max_connections(client) == 7
    spec = pools.provider_pool_spec(pools.PROVIDER_QWEN)
    assert spec is not None and spec.max_connections == 7


def test_global_env_applies_to_all_providers(monkeypatch):
    monkeypatch.setenv("MOGO_LLM_POOL_MAX_CONNECTIONS", "11")
    assert pools.provider_max_connections(pools.PROVIDER_AZURE_OPENAI) == 11
    assert pools.provider_max_connections(pools.PROVIDER_DEFAULT_OPENAI) == 11
    # provider 级 env 覆盖全局
    monkeypatch.setenv("MOGO_LLM_POOL_AZURE_OPENAI_MAX_CONNECTIONS", "4")
    assert pools.provider_max_connections(pools.PROVIDER_AZURE_OPENAI) == 4


def test_keepalive_never_exceeds_max_connections(monkeypatch):
    monkeypatch.setenv("MOGO_LLM_POOL_MAX_CONNECTIONS", "5")
    monkeypatch.setenv("MOGO_LLM_POOL_DEFAULT_OPENAI_MAX_KEEPALIVE_CONNECTIONS", "50")
    assert pools.provider_max_keepalive(pools.PROVIDER_DEFAULT_OPENAI) == 5


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_MAX_CONNECTIONS", "not-a-number")
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_TIMEOUT_SECONDS", "-3")
    assert (
        pools.provider_max_connections(pools.PROVIDER_QWEN)
        == pools.PROVIDER_POOL_MAX_CONNECTIONS_DEFAULT
    )
    assert pools.provider_http_timeout(pools.PROVIDER_QWEN) == pools.PROVIDER_HTTP_TIMEOUT_DEFAULT


def test_pool_key_namespace_is_prefixed():
    assert pools.pool_key("qwen") == "llm:qwen"
    assert pools.pool_key("mongodb") != "mongodb"


def test_summary_lists_only_llm_pools():
    registry = _fresh_registry()
    from app.common.dependency_guard import PoolSpec

    registry.register(PoolSpec("mongodb", max_connections=50))
    pools.register_provider_pool(pools.PROVIDER_QWEN, object(), registry=registry, max_connections=3)

    rows = pools.provider_pool_summary(registry=registry)
    assert [row["dependency"] for row in rows] == ["llm:qwen"]
    assert rows[0]["max_connections"] == 3
    # 未注入 stats_fn 时利用率如实为 None（不编造数字）
    assert rows[0]["utilization"] is None


def test_registered_pool_with_existing_key_updates_instead_of_raising():
    registry = _fresh_registry()
    pools.register_provider_pool("azure-openai", None, registry=registry, max_connections=2)
    spec = pools.register_provider_pool(
        "azure-openai", None, registry=registry, max_connections=9
    )
    assert spec.max_connections == 9
    assert len([s for s in registry.specs() if s.dependency == "llm:azure-openai"]) == 1


def test_clients_actually_use_the_isolated_http_client():
    """provider 必须把池句柄交给 SDK，否则登记只是纸面隔离。"""
    from app.llm.providers.azure_openai import AzureOpenAIClient
    from app.llm.providers.default_openai import DefaultOpenAIClient
    from app.llm.providers.qwen import QwenClient

    azure = AzureOpenAIClient(
        api_key="k",
        azure_endpoint="https://example.invalid",
        api_version="2024-10-21",
        azure_deployment="dep",
    )
    default = DefaultOpenAIClient(api_key="k", base_url="https://example.invalid/v1")
    qwen = QwenClient(api_key="k", base_url="https://example.invalid/v1", model="qwen-max")

    assert azure.client._client is pools.provider_http_client(pools.PROVIDER_AZURE_OPENAI)
    assert default.client._client is pools.provider_http_client(pools.PROVIDER_DEFAULT_OPENAI)
    assert qwen.client._client is pools.provider_http_client(pools.PROVIDER_QWEN)
    assert QwenClient.POOL_PROVIDER == pools.PROVIDER_QWEN
    assert DefaultOpenAIClient.POOL_PROVIDER == pools.PROVIDER_DEFAULT_OPENAI


def test_gpt_image_channel_registers_declared_limit():
    from app.llm.providers.azure_gpt_image import AzureGptImageClient, AzureGptImageConfig

    config = AzureGptImageConfig(
        endpoint="https://example.invalid",
        api_key="k",
        deployment="img",
        max_connections=2,
    )
    AzureGptImageClient(config)

    spec = pools.provider_pool_spec(pools.PROVIDER_AZURE_GPT_IMAGE)
    assert spec is not None
    assert spec.max_connections == 2
    # 每调用一支独立 httpx.Client，没有跨请求持久池句柄
    assert spec.pool is None
    assert spec.metadata.get("transport") == "per-call httpx.Client"


@pytest.mark.asyncio
async def test_aclose_provider_pools_releases_handles():
    client = pools.provider_http_client(pools.PROVIDER_QWEN)
    await pools.aclose_provider_pools()
    assert client.is_closed is True
    assert pools.provider_pool_spec(pools.PROVIDER_QWEN).pool is None


def test_pooled_client_is_rebound_when_event_loop_changes():
    """跨事件循环复用 httpx 池会永久挂起，因此换循环必须换句柄。

    回归背景：`tests/runtime/test_browser_effect_verification.py` 每个用例各自
    `asyncio.run()`；复用首个循环里创建的句柄会让第二个循环的调用挂死。
    """

    async def _grab() -> httpx.AsyncClient:
        return pools.provider_http_client(pools.PROVIDER_DEFAULT_OPENAI)

    first = asyncio.run(_grab())
    second = asyncio.run(_grab())

    assert first is not second
    assert pools.provider_pool_spec(pools.PROVIDER_DEFAULT_OPENAI).pool is second

    # 第三个循环（前一个已关闭）同样要新句柄：登记随之更新
    third = asyncio.run(_grab())
    assert third not in (first, second)
    assert pools.provider_pool_spec(pools.PROVIDER_DEFAULT_OPENAI).pool is third


@pytest.mark.asyncio
async def test_same_loop_reuses_handle_after_rebind():
    async def _grab() -> httpx.AsyncClient:
        return pools.provider_http_client(pools.PROVIDER_QWEN)

    first = await _grab()
    second = await _grab()
    assert first is second


def test_timeout_is_split_so_connect_does_not_inherit_read_budget(monkeypatch):
    """回归：`timeout=90` 会让「建连」也等 90s，黑洞网络下重试被拖成分钟级。"""
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("MOGO_LLM_POOL_QWEN_CONNECT_TIMEOUT_SECONDS", "4")
    client = pools.provider_http_client(pools.PROVIDER_QWEN)

    assert client.timeout.read == 60.0
    assert client.timeout.write == 60.0
    assert client.timeout.connect == 4.0
    assert client.timeout.pool == 4.0


def test_default_connect_timeout_matches_sdk_default():
    assert pools.provider_connect_timeout(pools.PROVIDER_AZURE_OPENAI) == 5.0
    # 读超时仍按 90s 的通道预算，两者互不影响
    spec = pools.provider_timeout(pools.PROVIDER_AZURE_OPENAI)
    assert spec.read == pools.PROVIDER_HTTP_TIMEOUT_DEFAULT
    assert spec.connect == pools.PROVIDER_CONNECT_TIMEOUT_DEFAULT
