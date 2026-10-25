"""023 T083/T084 — MongoDB / Redis 访问边界的熔断、超时与池登记。

**包装边界（如实口径）**：这里包的是「共享访问边界 + 健康检查」，不是在每条查询
外面套一层壳。理由：

* 业务查询面广且大多走 motor 的异步游标，逐条包 `asyncio.wait_for` 会把大结果集
  的流式迭代也计入 5s 预算，反而制造假超时；
* FR-21/FR-22 要防的是「坏依赖拖死整条链路」，只要**入口探测 + 共享客户端边界**
  被熔断器保护，依赖变坏时会话会被快速失败，不会把事件循环拖满。

因此落地为：

- `guarded_mongo_call()`：`call_with_breaker_async` + `TimeoutHierarchy.operation`
  （默认 5s）包一个**异步**调用（健康探测、启动自检、少量关键点）；
- `redis_call()`：同步 redis-py 客户端经熔断器执行；超时由驱动自己的
  `socket_timeout`（各客户端已设为 2s，< 5s 操作预算）承担——同步驱动无法在
  不引入线程的情况下强加超时，这一点在 tasks.md 里如实登记，不假装有 TimeoutGuard；
- `register_mongo_pool()` / `register_redis_pool()`：把**真实**池句柄与上限登记进
  `PoolRegistry`（上限从驱动读，不写死），让 FR-24 的隔离可断言、可观测；
- `probe_mongo()` / `probe_redis()`：健康检查统一出口，把熔断打开、超时、其它错误
  区分成稳定标签，`/ready` 据此返回 503 而不是抛异常。

本文件是 chat-api `app/core/resilience.py` 的 admin-api 孪生副本（两端访问边界一致，
仅服务内引用点不同）。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

from app.common.dependency_guard import (
    BREAKER_FAIL_MAX_DEFAULT,
    BREAKER_RESET_TIMEOUT_DEFAULT,
    CircuitOpenError,
    PoolRegistry,
    PoolSpec,
    TimeoutHierarchy,
    call_with_breaker,
    call_with_breaker_async,
    default_breaker_registry,
    default_pool_registry,
)

MONGO_DEPENDENCY = "mongodb"
REDIS_DEPENDENCY = "redis"

#: 两个客户端都没显式配置上限时的登记回退值（真实值优先从驱动读取）。
MONGO_POOL_MAX_CONNECTIONS_DEFAULT = 50
REDIS_POOL_MAX_CONNECTIONS_DEFAULT = 20

PROBE_OK = "ok"
PROBE_CIRCUIT_OPEN = "circuit_open"
PROBE_TIMEOUT = "timeout"
PROBE_ERROR = "error"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def operation_timeout_seconds() -> float:
    """单次依赖操作的超时预算（FR-22 第三层，默认 5s，env 可覆盖）。"""
    try:
        return TimeoutHierarchy.from_env().operation
    except Exception:
        # 层级被配倒挂时不要连带打死探测：退回默认预算并让配置校验报错。
        return 5.0


def _breaker(dependency: str):
    return default_breaker_registry.get_or_create(
        dependency,
        fail_max=_env_int("MOGO_BREAKER_FAIL_MAX", BREAKER_FAIL_MAX_DEFAULT),
        reset_timeout=_env_float(
            "MOGO_BREAKER_RESET_TIMEOUT_SECONDS", BREAKER_RESET_TIMEOUT_DEFAULT
        ),
    )


def mongo_breaker():
    return _breaker(MONGO_DEPENDENCY)


def redis_breaker():
    return _breaker(REDIS_DEPENDENCY)


# ───────────────────────── FR-24 池登记 ─────────────────────────


def _register(
    dependency: str,
    pool: Any,
    max_connections: int,
    *,
    registry: PoolRegistry | None = None,
    metadata: dict[str, Any] | None = None,
) -> PoolSpec:
    target = registry if registry is not None else default_pool_registry
    existing = target.get(dependency)
    if existing is not None:
        existing.pool = pool
        existing.max_connections = max_connections
        if metadata:
            existing.metadata.update(metadata)
        return existing
    spec = PoolSpec(
        dependency=dependency,
        max_connections=max_connections,
        pool=pool,
        metadata=dict(metadata or {}),
    )
    target.register(spec)
    return spec


def mongo_pool_max_connections(client: Any) -> int:
    """优先读驱动真实上限（motor/pymongo 的 `options.pool_options.max_pool_size`）。"""
    try:
        value = client.options.pool_options.max_pool_size
        if value:
            return int(value)
    except Exception:
        pass
    return _env_int("MOGO_MONGO_POOL_MAX_CONNECTIONS", MONGO_POOL_MAX_CONNECTIONS_DEFAULT)


def redis_pool_max_connections(client: Any) -> int:
    """优先读 redis-py `ConnectionPool.max_connections`。"""
    try:
        value = client.connection_pool.max_connections
        if value:
            return int(value)
    except Exception:
        pass
    return _env_int("MOGO_REDIS_POOL_MAX_CONNECTIONS", REDIS_POOL_MAX_CONNECTIONS_DEFAULT)


def register_mongo_pool(
    client: Any, *, registry: PoolRegistry | None = None
) -> PoolSpec:
    return _register(
        MONGO_DEPENDENCY,
        client,
        mongo_pool_max_connections(client),
        registry=registry,
        metadata={"pool": "motor.AsyncIOMotorClient"},
    )


def register_redis_pool(
    client: Any, *, registry: PoolRegistry | None = None
) -> PoolSpec:
    """登记 redis-py 的 `ConnectionPool` 句柄（不是 Redis 客户端本身）。"""
    handle = getattr(client, "connection_pool", client)
    return _register(
        REDIS_DEPENDENCY,
        handle,
        redis_pool_max_connections(client),
        registry=registry,
        metadata={"pool": "redis.ConnectionPool"},
    )


def release_pool(dependency: str, *, registry: PoolRegistry | None = None) -> None:
    """关闭客户端时解绑句柄，避免池表里留一个已关闭客户端的假句柄。"""
    target = registry if registry is not None else default_pool_registry
    spec = target.get(dependency)
    if spec is not None:
        spec.pool = None


def pool_spec(dependency: str, *, registry: PoolRegistry | None = None) -> PoolSpec | None:
    target = registry if registry is not None else default_pool_registry
    return target.get(dependency)


# ───────────────────────── 带熔断/超时的调用 ─────────────────────────


async def guarded_mongo_call(
    func: Callable[[], Any], *, timeout: float | None = None
) -> Any:
    """异步 Mongo 调用：熔断器 + 5s 操作预算。

    超时**发生在熔断器内部**（`wait_for` 包在 breaker 调用的协程里）：这样
    "依赖卡住" 会作为一次失败被 pybreaker 记数，连续超时同样能把熔断打开；
    若把 `wait_for` 套在 breaker 外层，`CancelledError` 不计失败，挂死的依赖
    永远不会熔断，每个请求都要白等 5s。
    """
    budget = operation_timeout_seconds() if timeout is None else timeout

    async def _bounded() -> Any:
        return await asyncio.wait_for(func(), timeout=budget)

    try:
        return await call_with_breaker_async(mongo_breaker(), _bounded)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise TimeoutError(f"mongodb operation exceeded {budget:.1f}s") from exc


def redis_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """同步 Redis 调用：经熔断器执行，超时由客户端 `socket_timeout` 承担。"""
    return call_with_breaker(redis_breaker(), func, *args, **kwargs)


async def guarded_redis_call(
    func: Callable[[], Any], *, timeout: float | None = None
) -> Any:
    """异步 Redis 调用（redis.asyncio 客户端用）：熔断器 + 操作预算。"""
    budget = operation_timeout_seconds() if timeout is None else timeout

    async def _bounded() -> Any:
        return await asyncio.wait_for(func(), timeout=budget)

    try:
        return await call_with_breaker_async(redis_breaker(), _bounded)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise TimeoutError(f"redis operation exceeded {budget:.1f}s") from exc


# ───────────────────────── 健康探测 ─────────────────────────


def _probe_payload(reason: str, **extra: Any) -> dict[str, Any]:
    return {"ok": reason == PROBE_OK, "reason": reason, **extra}


async def probe_mongo(database: Any, *, timeout: float | None = None) -> dict[str, Any]:
    """`/ready` 的 Mongo 探针：`database.admin.command('ping')` 走熔断 + 超时。"""

    async def _ping() -> Any:
        return await database.admin.command("ping")

    try:
        await guarded_mongo_call(_ping, timeout=timeout)
    except CircuitOpenError:
        return _probe_payload(PROBE_CIRCUIT_OPEN)
    except (asyncio.TimeoutError, TimeoutError):
        return _probe_payload(PROBE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — 探测失败一律转成不可达，不向上抛
        return _probe_payload(PROBE_ERROR, error=type(exc).__name__)
    return _probe_payload(PROBE_OK)


def probe_redis(client: Any, *, timeout: float | None = None) -> dict[str, Any]:
    """`/ready` 的 Redis 探针（同步驱动，超时由 socket_timeout 承担）。"""
    del timeout
    try:
        redis_call(client.ping)
    except CircuitOpenError:
        return _probe_payload(PROBE_CIRCUIT_OPEN)
    except Exception as exc:  # noqa: BLE001
        return _probe_payload(PROBE_ERROR, error=type(exc).__name__)
    return _probe_payload(PROBE_OK)
