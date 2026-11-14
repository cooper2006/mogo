"""023 T089 — 熔断器行为（FR-21）。

覆盖 `app.common.dependency_guard`：
连续失败达阈值 → 打开；打开态快速失败（不打到坏依赖上）；
冷却后半开试探：成功关闭 / 失败重新打开。
"""
from __future__ import annotations

import time

import pytest

from app.common.dependency_guard import (
    CIRCUIT_STATE_CLOSED,
    CIRCUIT_STATE_OPEN,
    BreakerRegistry,
    CircuitOpenError,
    breaker_failure_count,
    breaker_state,
    call_with_breaker,
    make_breaker,
)

COOLDOWN = 0.05


def _boom() -> str:
    raise RuntimeError("dependency down")


def _open_breaker(name: str = "mongodb", fail_max: int = 5):
    breaker = make_breaker(name, fail_max=fail_max, reset_timeout=COOLDOWN)
    for _ in range(fail_max):
        with pytest.raises(RuntimeError):
            call_with_breaker(breaker, _boom)
    return breaker


def test_consecutive_failures_open_the_circuit():
    """连续失败 5 次触发熔断。"""
    breaker = _open_breaker(fail_max=5)
    assert breaker_state(breaker) == CIRCUIT_STATE_OPEN
    assert breaker_failure_count(breaker) == 5


def test_open_circuit_fails_fast_without_calling_the_dependency():
    breaker = _open_breaker()
    calls = {"n": 0}

    def tracked() -> str:
        calls["n"] += 1
        return "ok"

    with pytest.raises(CircuitOpenError) as exc:
        call_with_breaker(breaker, tracked)
    assert exc.value.dependency == "mongodb"
    # 关键：熔断打开后底层依赖一次都不该被调用。
    assert calls["n"] == 0


def test_half_open_probe_success_closes_the_circuit():
    """冷却后半开试探成功 → 关闭。"""
    breaker = _open_breaker()
    time.sleep(COOLDOWN * 2)
    assert call_with_breaker(breaker, lambda: "ok") == "ok"
    assert breaker_state(breaker) == CIRCUIT_STATE_CLOSED


def test_half_open_probe_failure_reopens_the_circuit():
    """半开试探失败 → 重新打开（不要放行剩余流量）。"""
    breaker = _open_breaker()
    time.sleep(COOLDOWN * 2)
    with pytest.raises(CircuitOpenError):
        call_with_breaker(breaker, _boom)
    assert breaker_state(breaker) == CIRCUIT_STATE_OPEN


def test_excluded_exception_does_not_count_as_dependency_failure():
    """业务异常（4xx 类）不计入熔断 —— 否则一次参数错误会把依赖熔断掉。"""
    breaker = make_breaker("llm", fail_max=2, reset_timeout=COOLDOWN, exclude=[ValueError])

    def bad_input() -> str:
        raise ValueError("bad prompt")

    for _ in range(5):
        with pytest.raises(ValueError):
            call_with_breaker(breaker, bad_input)
    assert breaker_state(breaker) == CIRCUIT_STATE_CLOSED


def test_breaker_registry_returns_one_breaker_per_dependency():
    """每个依赖一个 breaker：不能共享，否则 Mongo 挂掉会连带Redis 请求也被熔断。"""
    registry = BreakerRegistry()
    mongo = registry.get_or_create("mongodb")
    redis = registry.get_or_create("redis")
    again = registry.get_or_create("mongodb")
    registry.reset()
    try:
        assert mongo is not redis
        assert again is mongo
    finally:
        pass
