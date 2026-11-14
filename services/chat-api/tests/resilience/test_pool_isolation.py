"""023 T092 — 资源池隔离（FR-24）。

关键依赖各自独立池：Mongo 慢查询不能把 Redis 池耗光。
"""
from __future__ import annotations

import pytest

from app.common.dependency_guard import PoolRegistry, PoolSpec


def test_pools_are_registered_per_dependency():
    registry = PoolRegistry()
    mongo_pool = object()
    redis_pool = object()
    registry.register(PoolSpec("mongodb", max_connections=50, pool=mongo_pool))
    registry.register(PoolSpec("redis", max_connections=20, pool=redis_pool))

    assert registry.get("mongodb").pool is mongo_pool
    assert registry.get("redis").pool is redis_pool
    assert len({id(s.pool) for s in registry.specs()}) == 2
    assert registry.shared_handle_count() == {}


def test_duplicate_registration_is_rejected():
    """同一依赖注册两次 = 两个池抢同一配额，必须拒绝。"""
    registry = PoolRegistry()
    registry.register(PoolSpec("mongodb", max_connections=50))
    with pytest.raises(ValueError):
        registry.register(PoolSpec("mongodb", max_connections=10))


def test_shared_handle_between_dependencies_is_detected():
    registry = PoolRegistry()
    shared = object()
    registry.register(PoolSpec("mongodb", max_connections=50, pool=shared))
    registry.register(PoolSpec("redis", max_connections=20, pool=shared))
    problems = registry.shared_handle_count()
    assert len(problems) == 1
    assert sorted(next(iter(problems.values()))) == ["mongodb", "redis"]


def test_utilization_uses_injected_stats():
    registry = PoolRegistry()
    registry.register(
        PoolSpec(
            "mongodb",
            max_connections=10,
            stats_fn=lambda: {"checked_out": 5, "max": 10},
        )
    )
    assert registry.get("mongodb").utilization() == pytest.approx(0.5)


def test_utilization_is_none_without_stats_probe():
    spec = PoolSpec("redis", max_connections=10)
    assert spec.utilization() is None


def test_utilization_survives_failing_probe():
    """采集探针炸了不能反过来打断 /ready。"""
    def boom():
        raise RuntimeError("stats unavailable")

    spec = PoolSpec("redis", max_connections=10, stats_fn=boom)
    assert spec.utilization() is None


def test_breaking_pool_does_not_affect_other_dependency():
    """隔离的语义断言：Mongo 池耗尽的观测不应改变 Redis 池的利用率。"""
    registry = PoolRegistry()
    registry.register(PoolSpec("mongodb", max_connections=10, stats_fn=lambda: {"checked_out": 10}))
    registry.register(PoolSpec("redis", max_connections=10, stats_fn=lambda: {"checked_out": 1}))
    assert registry.get("mongodb").utilization() == pytest.approx(1.0)
    assert registry.get("redis").utilization() == pytest.approx(0.1)
