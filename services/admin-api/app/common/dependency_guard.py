"""023 T004 — 依赖守护基类：熔断 / 超时 / 重试 / 资源池隔离（权威源）。

vendored 副本纪律见 `observability_base.py` 头注（改本文件须同步三服务副本，
`scripts/check_common_sync.py` 在 CI 校验字节一致）。

口径（spec Clarify 决策 2026-10-24）：
- 熔断库 = **pybreaker**（OQ-3）：默认连续失败 5 次打开、30s 后半开试探 1 个请求
  （FR-21）。半开成功→关闭，失败→重新打开，为 pybreaker 内建语义。
- 超时层级（FR-22）：入口 30s > 下游服务调用 10s > 单次 LLM/DB 操作 5s。
  本模块提供 `layered_timeout()` 返回三层默认值并可被配置覆盖；执行层在各自
  服务接线（httpx timeout / motor max_time_ms），这里只统一常量与校验
  （入口 ≤ 上层预算的约束在构造时报错，防层级倒挂）。
- 重试（FR-23）：指数退避 + 抖动，基数 1.5s / 上限 30s / ±10% / 最多 3 次，
  **与 007 完全一致**——007 已在 LLM 调用级实现，本模块只负责非 LLM 依赖
  （MongoDB/Redis/HTTP 下游），可重试错误限定 429/5xx/超时（401/403 立即失败）。
- 资源池隔离（FR-24）：`PoolRegistry` 登记每依赖独立池句柄与上限，供健康检查
  与指标采集读取；不同依赖不得共享同一 key。

设计约束：本模块不 import 任何服务私有模块（纯依赖层），保证可被三服务 vendor。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, TypeVar

import pybreaker

T = TypeVar("T")

# ─────────────────────────── FR-21 熔断 ───────────────────────────

BREAKER_FAIL_MAX_DEFAULT = 5
BREAKER_RESET_TIMEOUT_DEFAULT = 30.0
BREAKER_SUCCESS_THRESHOLD_DEFAULT = 1


class CircuitOpenError(RuntimeError):
    """熔断打开时的快速失败（FR-21：后续请求快速失败，不打到坏依赖上）。"""

    def __init__(self, dependency: str) -> None:
        super().__init__(f"circuit open for dependency: {dependency}")
        self.dependency = dependency


def make_breaker(
    name: str,
    *,
    fail_max: int = BREAKER_FAIL_MAX_DEFAULT,
    reset_timeout: float = BREAKER_RESET_TIMEOUT_DEFAULT,
    success_threshold: int = BREAKER_SUCCESS_THRESHOLD_DEFAULT,
    exclude: Iterable[Any] | None = None,
) -> pybreaker.CircuitBreaker:
    """创建依赖专属熔断器。`exclude` 中的异常不计为失败（业务错误≠依赖故障）。"""
    return pybreaker.CircuitBreaker(
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        success_threshold=success_threshold,
        exclude=list(exclude or []),
        name=name,
    )


def call_with_breaker(
    breaker: pybreaker.CircuitBreaker, func: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    try:
        return breaker.call(func, *args, **kwargs)
    except pybreaker.CircuitBreakerError as exc:  # tripped 或半开失败重开
        raise CircuitOpenError(breaker.name or "unknown") from exc


async def call_with_breaker_async(
    breaker: pybreaker.CircuitBreaker, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    try:
        return await breaker.call_async(func, *args, **kwargs)
    except pybreaker.CircuitBreakerError as exc:
        raise CircuitOpenError(breaker.name or "unknown") from exc


# ─────────────────────────── FR-22 超时层级 ───────────────────────────

TIMEOUT_ENTRY_SECONDS_DEFAULT = 30.0
TIMEOUT_DOWNSTREAM_SECONDS_DEFAULT = 10.0
TIMEOUT_OPERATION_SECONDS_DEFAULT = 5.0


class TimeoutHierarchyError(ValueError):
    """层级倒挂：下层超时不得 ≥ 上层（否则上层先死，预算失效）。"""


@dataclass(frozen=True)
class TimeoutHierarchy:
    entry: float = TIMEOUT_ENTRY_SECONDS_DEFAULT
    downstream: float = TIMEOUT_DOWNSTREAM_SECONDS_DEFAULT
    operation: float = TIMEOUT_OPERATION_SECONDS_DEFAULT

    def __post_init__(self) -> None:
        if not (self.operation < self.downstream < self.entry):
            raise TimeoutHierarchyError(
                f"need operation < downstream < entry, got "
                f"{self.operation}/{self.downstream}/{self.entry}"
            )

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "TimeoutHierarchy":
        import os

        env = environ if environ is not None else os.environ

        def _f(key: str, fallback: float) -> float:
            raw = env.get(key, "")
            try:
                return float(raw) if raw else fallback
            except ValueError:
                return fallback

        return cls(
            entry=_f("MOGO_TIMEOUT_ENTRY_SECONDS", cls.entry),
            downstream=_f("MOGO_TIMEOUT_DOWNSTREAM_SECONDS", cls.downstream),
            operation=_f("MOGO_TIMEOUT_OPERATION_SECONDS", cls.operation),
        )


# ─────────────────────────── FR-23 重试 ───────────────────────────

RETRY_BASE_SECONDS = 1.5
RETRY_MAX_SECONDS = 30.0
RETRY_JITTER_RATIO = 0.10
RETRY_MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def backoff_delay(attempt: int) -> float:
    """指数退避 + ±10% 抖动。attempt 从 1 起（第 n 次失败后的等待）。"""
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    base = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
    jitter = base * RETRY_JITTER_RATIO
    return max(0.0, base + random.uniform(-jitter, jitter))


def is_retryable_status(status_code: int) -> bool:
    """429/5xx 可重试；401/403 与其他 4xx 立即失败（FR-23）。"""
    return status_code in RETRYABLE_STATUS


def retry_sync(
    func: Callable[[], T],
    *,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """同步重试执行器；每次失败 sleep backoff_delay(attempt)。"""
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except retry_on as exc:
            last = exc
            if attempt < max_attempts:
                sleep(backoff_delay(attempt))
    assert last is not None
    raise last


async def retry_async(
    func: Callable[[], Any],
    *,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
    sleep: Callable[[float], Any] | None = None,
) -> Any:
    """异步重试执行器（`await func()`；sleep 注入便于测试不真等）。"""
    import asyncio

    _sleep = sleep or asyncio.sleep
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await func()
        except retry_on as exc:
            last = exc
            if attempt < max_attempts:
                await _sleep(backoff_delay(attempt))
    assert last is not None
    raise last


# ─────────────────────────── FR-24 资源池隔离 ───────────────────────────


@dataclass
class PoolSpec:
    dependency: str          # "mongodb" / "redis" / "llm-http" / 服务名
    max_connections: int
    pool: Any = None         # 实际句柄由服务注册；这里只做登记与巡检
    stats_fn: Callable[[], dict[str, Any]] | None = None  # 服务侧注入利用率采集
    metadata: dict[str, Any] = field(default_factory=dict)

    def utilization(self) -> float | None:
        """经注入的 `stats_fn` 探测利用率（0~1）；未注入或采集失败返回 None。"""
        if self.stats_fn is None:
            return None
        try:
            stats = self.stats_fn()
            used = float(stats.get("checked_out") or stats.get("in_use") or 0)
            total = float(stats.get("max") or self.max_connections) or float(
                self.max_connections
            )
            return used / total if total > 0 else None
        except Exception:
            return None


class PoolRegistry:
    """进程内资源池登记表（FR-24）。同一 dependency 重复注册即隔离违规。"""

    def __init__(self) -> None:
        self._specs: dict[str, PoolSpec] = {}

    def register(self, spec: PoolSpec) -> None:
        if spec.dependency in self._specs:
            raise ValueError(f"pool already registered: {spec.dependency}")
        self._specs[spec.dependency] = spec

    def get(self, dependency: str) -> PoolSpec | None:
        return self._specs.get(dependency)

    def specs(self) -> list[PoolSpec]:
        return list(self._specs.values())

    def shared_handle_count(self) -> dict[str, list[str]]:
        """检测同一池句柄被登记给多个依赖 key（共享=违反隔离）。"""
        by_id: dict[int, list[str]] = {}
        for spec in self._specs.values():
            if spec.pool is not None:
                by_id.setdefault(id(spec.pool), []).append(spec.dependency)
        return {k: v for k, v in by_id.items() if len(v) > 1}


default_pool_registry = PoolRegistry()
