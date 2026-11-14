"""LLM 通道级资源池隔离（FR-24 / 023 T082）。

任务书 T082 要求「各 provider 用 ConnectionPool 包装（独立池）」。这里的落地口径是：

1. **每个 provider 一个进程级独立 httpx 连接池**（各自 `httpx.Limits`），不再共用
   openai SDK 默认创建的隐式池——否则 azure 与 qwen 抢同一份配额，一个通道打满
   会把另一个通道饿死。
2. **每个 provider 在 `PoolRegistry` 里登记为独立依赖 key**（`llm:<provider>`），
   供健康检查、指标与 `tests/resilience/test_pool_isolation.py` 的隔离断言使用。
   同一 provider 重复构造客户端时复用同一句柄并更新上限，不会触发
   `PoolRegistry.register` 的「重复注册」拒绝。
3. **利用率探针（`PoolSpec.stats_fn`）默认留空**：httpx / httpcore 未暴露
   「当前检出连接数」的稳定计数器，硬凑一个会给出假利用率，故如实登记为未接入，
   需要时由调用侧用 `stats_fn` 参数注入。
4. **句柄按事件循环绑定**：`httpx.AsyncClient` 的连接池绑定在首次使用的循环上，
   跨循环复用的后果是调用永久挂起（不是报错）。生产是单循环、天然一个句柄；
   测试里每个用例 `asyncio.run()` 各开一个循环，所以这里按「循环变了就换新句柄」
   处理——旧句柄的连接属于已关闭的循环，直接丢弃而不 `aclose()`（关闭会卡住）。

`azure-responses` 说明：`app/llm/providers/azure_responses.py` 已退化为
`ConfiguredMultimodalClient` 的兼容别名，真实流量经 `app/llm/configured_models.py`
构造 `AzureOpenAIClient` / `DefaultOpenAIClient`，因此它的池就是
`llm:azure-openai` / `llm:default-openai`，**不再单独登记一个不存在的传输层**。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

import httpx

from app.common.dependency_guard import (
    PoolRegistry,
    PoolSpec,
    default_pool_registry,
)

__all__ = [
    "PROVIDER_AZURE_GPT_IMAGE",
    "PROVIDER_AZURE_OPENAI",
    "PROVIDER_DEFAULT_OPENAI",
    "PROVIDER_QWEN",
    "aclose_provider_pools",
    "pool_key",
    "provider_http_client",
    "provider_max_connections",
    "provider_max_keepalive",
    "provider_pool_spec",
    "provider_timeout",
    "provider_pool_summary",
    "register_provider_pool",
    "reset_provider_pools",
]

PROVIDER_AZURE_OPENAI = "azure-openai"
PROVIDER_AZURE_GPT_IMAGE = "azure-gpt-image"
PROVIDER_DEFAULT_OPENAI = "default-openai"
PROVIDER_QWEN = "qwen"

#: 单 provider 默认连接上限。LLM 调用是长尾 IO，20 条并发足以打满单通道，
#: 再高只是把上游 429 提前搬到本地排队。
PROVIDER_POOL_MAX_CONNECTIONS_DEFAULT = 20
PROVIDER_POOL_MAX_KEEPALIVE_DEFAULT = 10
PROVIDER_HTTP_TIMEOUT_DEFAULT = 90.0
#: 连接超时必须比读超时短得多（对齐 openai SDK 的 5s connect 默认值）：
#: 网络黑洞（SYN 被丢弃）时，若 connect 也按 90s 读超时算，三次重试会拖到 4 分钟
#: 才失败——线上表现为「请求卡死」，故障时反而比不重试更糟。
PROVIDER_CONNECT_TIMEOUT_DEFAULT = 5.0

_ENV_PREFIX = "MOGO_LLM_POOL_"


def pool_key(provider: str) -> str:
    """依赖登记 key——故意带 `llm:` 前缀，避免与 `mongodb` / `redis` 撞名。"""
    return f"llm:{str(provider or '').strip()}"


def _env_suffix(provider: str) -> str:
    return str(provider or "").strip().upper().replace("-", "_")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def provider_max_connections(provider: str, default: int | None = None) -> int:
    """上限优先取 `MOGO_LLM_POOL_<PROVIDER>_MAX_CONNECTIONS`，其次全局，最后默认值。"""
    fallback = default or _env_int(
        f"{_ENV_PREFIX}MAX_CONNECTIONS", PROVIDER_POOL_MAX_CONNECTIONS_DEFAULT
    )
    return _env_int(f"{_ENV_PREFIX}{_env_suffix(provider)}_MAX_CONNECTIONS", fallback)


def provider_max_keepalive(provider: str) -> int:
    kept = _env_int(
        f"{_ENV_PREFIX}{_env_suffix(provider)}_MAX_KEEPALIVE_CONNECTIONS",
        _env_int(f"{_ENV_PREFIX}MAX_KEEPALIVE_CONNECTIONS", PROVIDER_POOL_MAX_KEEPALIVE_DEFAULT),
    )
    # keepalive 不能超过总上限，否则 httpx 会静默按上限截断，配置与实测对不上。
    return max(0, min(kept, provider_max_connections(provider)))


def provider_connect_timeout(provider: str) -> float:
    """建连超时：优先单 provider env，其次全局，最后 5s，且不超过总超时。"""
    raw = os.getenv(f"{_ENV_PREFIX}{_env_suffix(provider)}_CONNECT_TIMEOUT_SECONDS")
    value = PROVIDER_CONNECT_TIMEOUT_DEFAULT
    if raw is not None and str(raw).strip():
        try:
            parsed = float(str(raw).strip())
        except (TypeError, ValueError):
            parsed = value
        else:
            if parsed > 0:
                value = parsed
    return min(value, provider_http_timeout(provider))


def provider_timeout(provider: str, *, total: float | None = None) -> httpx.Timeout:
    """按 httpx 的语义拆分超时：连接/排队短，读长。

    把 `timeout=90` 直接传给 `httpx.AsyncClient` 会让「连接」也用 90s，
    黑洞网络下每次重试都要等满，故这里显式给出分档值。
    """
    read = total if total is not None else provider_http_timeout(provider)
    connect = min(provider_connect_timeout(provider), read)
    return httpx.Timeout(read, connect=connect, write=read, pool=connect)


def provider_http_timeout(provider: str) -> float:
    raw = os.getenv(f"{_ENV_PREFIX}{_env_suffix(provider)}_TIMEOUT_SECONDS")
    if raw is None or not str(raw).strip():
        return PROVIDER_HTTP_TIMEOUT_DEFAULT
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return PROVIDER_HTTP_TIMEOUT_DEFAULT
    return value if value > 0 else PROVIDER_HTTP_TIMEOUT_DEFAULT


class _PooledClient:
    """一个 provider 的连接池句柄，以及它所属的事件循环。"""

    __slots__ = ("client", "loop")

    def __init__(self, client: httpx.AsyncClient, loop: Any) -> None:
        self.client = client
        self.loop = loop

    def usable_in(self, loop: Any) -> bool:
        """句柄只有在「同一个、仍存活」的循环里才能复用。"""
        if self.client.is_closed:
            return False
        if self.loop is loop:
            return loop is None or not loop.is_closed()
        return False


def _current_loop() -> Any:
    """取当前运行中的循环；在同步上下文里调用则返回 None（此时无绑定）。"""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


# provider -> 进程级独立连接池句柄（含所属循环）
_clients: dict[str, _PooledClient] = {}
# provider -> 调用侧注入的利用率采集函数（默认无）
_stats_fns: dict[str, Callable[[], dict[str, Any]]] = {}


def _registry(registry: PoolRegistry | None) -> PoolRegistry:
    return registry if registry is not None else default_pool_registry


def build_httpx_limits(provider: str) -> httpx.Limits:
    return httpx.Limits(
        max_connections=provider_max_connections(provider),
        max_keepalive_connections=provider_max_keepalive(provider),
    )


def register_provider_pool(
    provider: str,
    pool: Any,
    *,
    max_connections: int | None = None,
    stats_fn: Callable[[], dict[str, Any]] | None = None,
    registry: PoolRegistry | None = None,
    metadata: dict[str, Any] | None = None,
) -> PoolSpec:
    """登记（或更新）一个 provider 的池。

    `PoolRegistry.register` 遇到重复 key 抛 `ValueError` 是刻意的隔离保护；但 LLM
    客户端是**按需构造**的（factory 每次请求都可能新建），重复构造同一 provider
    不是隔离违规，所以这里用「已存在则更新句柄与上限」的语义包一层。
    """
    target = _registry(registry)
    key = pool_key(provider)
    limit = max_connections or provider_max_connections(provider)
    extra = dict(metadata or {})
    resolved_stats = stats_fn if stats_fn is not None else _stats_fns.get(provider)
    existing = target.get(key)
    if existing is not None:
        existing.pool = pool
        existing.max_connections = limit
        if resolved_stats is not None:
            existing.stats_fn = resolved_stats
        if extra:
            existing.metadata.update(extra)
        return existing
    spec = PoolSpec(
        dependency=key,
        max_connections=limit,
        pool=pool,
        stats_fn=resolved_stats,
        metadata={"provider": provider, **extra},
    )
    target.register(spec)
    return spec


def provider_pool_spec(provider: str, *, registry: PoolRegistry | None = None) -> PoolSpec | None:
    return _registry(registry).get(pool_key(provider))


def provider_http_client(
    provider: str,
    *,
    registry: PoolRegistry | None = None,
    timeout: float | None = None,
    stats_fn: Callable[[], dict[str, Any]] | None = None,
) -> httpx.AsyncClient:
    """取（必要时创建）该 provider 的独立连接池句柄。"""
    if stats_fn is not None:
        _stats_fns[provider] = stats_fn
    loop = _current_loop()
    entry = _clients.get(provider)
    if entry is not None and entry.usable_in(loop):
        return entry.client
    # 循环变了（换循环 / 旧循环已关闭）：旧句柄会跨循环复用导致调用挂死，
    # 直接换新句柄；旧的不 aclose()——它的连接属于已关闭的循环，关闭会卡住。
    client = httpx.AsyncClient(
        limits=build_httpx_limits(provider),
        timeout=provider_timeout(provider, total=timeout),
    )
    _clients[provider] = _PooledClient(client, loop)
    register_provider_pool(
        provider,
        client,
        stats_fn=stats_fn,
        registry=registry,
        metadata={"transport": "httpx.AsyncClient"},
    )
    return client


def provider_pool_summary(registry: PoolRegistry | None = None) -> list[dict[str, Any]]:
    """排障用快照：每个 LLM 池的上限与（可得的）利用率。"""
    rows: list[dict[str, Any]] = []
    for spec in _registry(registry).specs():
        if not spec.dependency.startswith("llm:"):
            continue
        rows.append(
            {
                "dependency": spec.dependency,
                "provider": spec.metadata.get("provider", ""),
                "max_connections": spec.max_connections,
                "utilization": spec.utilization(),
            }
        )
    return rows


def reset_provider_pools(registry: PoolRegistry | None = None) -> None:
    """测试用：丢弃句柄并解绑登记（不关闭连接，关闭走 `aclose_provider_pools`）。"""
    target = _registry(registry)
    for provider in list(_clients):
        spec = target.get(pool_key(provider))
        if spec is not None:
            spec.pool = None
    _clients.clear()
    _stats_fns.clear()


async def aclose_provider_pools(registry: PoolRegistry | None = None) -> None:
    """进程退出 / 测试收尾：关闭全部 provider 连接池。"""
    target = _registry(registry)
    loop = _current_loop()
    for provider, entry in list(_clients.items()):
        spec = target.get(pool_key(provider))
        if spec is not None:
            spec.pool = None
        if loop is not None and entry.loop is not loop:
            # 别的循环留下的句柄：在错误循环里 aclose() 会挂住，直接丢弃。
            continue
        try:
            await entry.client.aclose()
        except Exception:
            # 关闭失败不该阻断进程退出：句柄已解绑，泄漏面仅剩一个空壳对象。
            pass
    _clients.clear()
    _stats_fns.clear()
