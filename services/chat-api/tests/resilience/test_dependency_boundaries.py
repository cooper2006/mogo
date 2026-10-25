"""023 T083/T084 — Mongo / Redis 访问边界的熔断、超时与池登记。

覆盖：熔断打开后的快速失败、超时预算、探测结果标签、池句柄与真实上限登记、
客户端关闭时解绑句柄、以及两个服务共享同一口径。
"""

from __future__ import annotations

import asyncio

import pytest

from app.common.dependency_guard import (
    BreakerRegistry,
    CircuitOpenError,
    PoolRegistry,
    default_breaker_registry,
)
from app.core import resilience


@pytest.fixture(autouse=True)
def _isolate_breakers():
    default_breaker_registry.reset()
    yield
    default_breaker_registry.reset()


class _FakeAdmin:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = 0

    async def command(self, name):  # noqa: D401 - 模拟 motor admin
        self.calls += 1
        return await self._behaviour()


class _FakeDatabase:
    """最小 motor Database 形状：只需要 `.admin.command('ping')`。"""

    def __init__(self, behaviour):
        self.admin = _FakeAdmin(behaviour)


class _FakePoolOptions:
    def __init__(self, max_pool_size):
        self.max_pool_size = max_pool_size


class _FakeOptions:
    def __init__(self, max_pool_size):
        self.pool_options = _FakePoolOptions(max_pool_size)


class _FakeMongoClient:
    def __init__(self, max_pool_size=100):
        self.options = _FakeOptions(max_pool_size)


class _FakeRedisPool:
    def __init__(self, max_connections):
        self.max_connections = max_connections


class _FakeRedis:
    def __init__(self, *, max_connections=20, fail=False):
        self.connection_pool = _FakeRedisPool(max_connections)
        self.fail = fail
        self.pings = 0

    def ping(self):
        self.pings += 1
        if self.fail:
            raise ConnectionError("redis down")
        return True


# ───────────────────────── 超时 ─────────────────────────


@pytest.mark.asyncio
async def test_mongo_timeout_raises_and_is_counted_as_failure():
    async def _hang():
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await resilience.guarded_mongo_call(_hang, timeout=0.01)

    # 超时进熔断器内部，因此算一次失败（否则挂死的依赖永远不熔断）
    assert resilience.mongo_breaker().fail_counter == 1


@pytest.mark.asyncio
async def test_mongo_call_returns_value_on_success():
    async def _ok():
        return {"ok": 1}

    assert await resilience.guarded_mongo_call(_ok, timeout=1.0) == {"ok": 1}
    assert resilience.mongo_breaker().fail_counter == 0


# ───────────────────────── 熔断 ─────────────────────────


@pytest.mark.asyncio
async def test_mongo_breaker_opens_after_consecutive_failures():
    async def _boom():
        raise RuntimeError("mongo down")

    breaker = resilience.mongo_breaker()
    # 第 fail_max 次失败时 pybreaker 直接抛熔断错误（计数到阈即打开），
    # 所以前 fail_max-1 次是原始异常，第 fail_max 次起是 CircuitOpenError。
    for _ in range(breaker.fail_max - 1):
        with pytest.raises(RuntimeError):
            await resilience.guarded_mongo_call(_boom, timeout=1.0)

    with pytest.raises(CircuitOpenError):
        await resilience.guarded_mongo_call(_boom, timeout=1.0)
    with pytest.raises(CircuitOpenError):
        await resilience.guarded_mongo_call(_boom, timeout=1.0)


@pytest.mark.asyncio
async def test_probe_reports_circuit_open_without_calling_dependency():
    async def _boom():
        raise RuntimeError("mongo down")

    database = _FakeDatabase(_boom)
    for _ in range(resilience.mongo_breaker().fail_max):
        assert (await resilience.probe_mongo(database))["ok"] is False
    calls_before = database.admin.calls

    result = await resilience.probe_mongo(database)
    assert result == {"ok": False, "reason": resilience.PROBE_CIRCUIT_OPEN}
    assert database.admin.calls == calls_before  # 熔断打开时不再打到坏依赖


@pytest.mark.asyncio
async def test_probe_reports_timeout():
    async def _hang():
        await asyncio.sleep(5)

    result = await resilience.probe_mongo(_FakeDatabase(_hang), timeout=0.01)
    assert result == {"ok": False, "reason": resilience.PROBE_TIMEOUT}


@pytest.mark.asyncio
async def test_probe_reports_error_and_ok():
    async def _boom():
        raise RuntimeError("mongo down")

    async def _ok():
        return {"ok": 1}

    assert (await resilience.probe_mongo(_FakeDatabase(_boom)))["reason"] == resilience.PROBE_ERROR
    assert await resilience.probe_mongo(_FakeDatabase(_ok)) == {
        "ok": True,
        "reason": resilience.PROBE_OK,
    }


@pytest.mark.asyncio
async def test_probe_includes_error_type_for_triage():
    async def _boom():
        raise PermissionError("auth failed")

    result = await resilience.probe_mongo(_FakeDatabase(_boom))
    assert result["ok"] is False
    assert result["error"] == "PermissionError"


# ───────────────────────── Redis 边界 ─────────────────────────


def test_redis_call_goes_through_breaker():
    client = _FakeRedis(fail=True)
    breaker = resilience.redis_breaker()
    for _ in range(breaker.fail_max - 1):
        with pytest.raises(ConnectionError):
            resilience.redis_call(client.ping)

    # 阈值那一次仍然打到了依赖（失败计数到阈值后随即打开）
    with pytest.raises(CircuitOpenError):
        resilience.redis_call(client.ping)
    assert client.pings == breaker.fail_max

    # 打开之后快速失败，不再打到坏依赖
    with pytest.raises(CircuitOpenError):
        resilience.redis_call(client.ping)
    assert client.pings == breaker.fail_max


def test_redis_probe_reports_unreachable():
    client = _FakeRedis(fail=True)
    result = resilience.probe_redis(client)
    assert result["ok"] is False
    assert result["reason"] == resilience.PROBE_ERROR


def test_redis_probe_ok():
    assert resilience.probe_redis(_FakeRedis()) == {
        "ok": True,
        "reason": resilience.PROBE_OK,
    }


# ───────────────────────── 池登记（FR-24）─────────────────────────


def test_mongo_pool_limit_read_from_driver_not_hardcoded(monkeypatch):
    monkeypatch.setenv("MOGO_MONGO_POOL_MAX_CONNECTIONS", "7")
    registry = PoolRegistry()
    client = _FakeMongoClient(max_pool_size=37)

    spec = resilience.register_mongo_pool(client, registry=registry)

    assert spec.dependency == "mongodb"
    assert spec.pool is client
    assert spec.max_connections == 37  # 驱动真实上限优先于 env 回退值


def test_mongo_pool_registration_is_idempotent():
    registry = PoolRegistry()
    first = _FakeMongoClient(max_pool_size=100)
    second = _FakeMongoClient(max_pool_size=60)

    resilience.register_mongo_pool(first, registry=registry)
    spec = resilience.register_mongo_pool(second, registry=registry)

    assert spec.pool is second
    assert spec.max_connections == 60
    assert len([s for s in registry.specs() if s.dependency == "mongodb"]) == 1


def test_redis_pool_registers_connection_pool_handle():
    registry = PoolRegistry()
    client = _FakeRedis(max_connections=13)

    spec = resilience.register_redis_pool(client, registry=registry)

    assert spec.dependency == "redis"
    assert spec.pool is client.connection_pool
    assert spec.max_connections == 13


def test_mongo_and_redis_pools_are_isolated():
    registry = PoolRegistry()
    resilience.register_mongo_pool(_FakeMongoClient(), registry=registry)
    resilience.register_redis_pool(_FakeRedis(), registry=registry)

    assert registry.get("mongodb").pool is not registry.get("redis").pool
    assert registry.shared_handle_count() == {}


def test_release_pool_unbinds_closed_client():
    registry = PoolRegistry()
    resilience.register_mongo_pool(_FakeMongoClient(), registry=registry)

    resilience.release_pool("mongodb", registry=registry)

    assert registry.get("mongodb").pool is None


def test_breaker_registry_is_per_dependency():
    registry = BreakerRegistry()
    mongo = registry.get_or_create("mongodb")
    redis = registry.get_or_create("redis")
    assert mongo is not redis
    assert registry.names() == ["mongodb", "redis"]


def test_operation_timeout_defaults_to_five_seconds(monkeypatch):
    monkeypatch.delenv("MOGO_TIMEOUT_OPERATION_SECONDS", raising=False)
    assert resilience.operation_timeout_seconds() == 5.0


def test_operation_timeout_follows_env(monkeypatch):
    monkeypatch.setenv("MOGO_TIMEOUT_ENTRY_SECONDS", "20")
    monkeypatch.setenv("MOGO_TIMEOUT_DOWNSTREAM_SECONDS", "8")
    monkeypatch.setenv("MOGO_TIMEOUT_OPERATION_SECONDS", "3")
    assert resilience.operation_timeout_seconds() == 3.0


def test_inverted_timeout_hierarchy_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("MOGO_TIMEOUT_ENTRY_SECONDS", "1")
    monkeypatch.setenv("MOGO_TIMEOUT_DOWNSTREAM_SECONDS", "2")
    monkeypatch.setenv("MOGO_TIMEOUT_OPERATION_SECONDS", "3")
    # 倒挂配置会让 TimeoutHierarchy 构造报错；探测不能因此连带失效
    assert resilience.operation_timeout_seconds() == 5.0
