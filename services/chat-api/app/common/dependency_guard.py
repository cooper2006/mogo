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


def _async_ready_state(
    breaker: pybreaker.CircuitBreaker,
) -> pybreaker.CircuitBreakerState:
    """为异步调用准备熔断状态：OPEN 且冷却已过则推进到 HALF_OPEN。

    pybreaker 1.4 只在 `CircuitOpenState.before_call()` 里做这个推进，而那条路径
    会同步 `call()` 一个协程函数（对 async 无意义），所以这里自己走一遍。
    """
    from datetime import datetime, timedelta, timezone

    state = breaker.state
    if type(state).__name__ != "CircuitOpenState":
        return state
    opened_at = getattr(breaker._state_storage, "opened_at", None)
    if opened_at and datetime.now(timezone.utc) >= opened_at + timedelta(
        seconds=breaker.reset_timeout
    ):
        breaker.half_open()
        return breaker.state
    raise CircuitOpenError(breaker.name or "unknown")


async def call_with_breaker_async(
    breaker: pybreaker.CircuitBreaker, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """异步熔断调用。

    为什么不用 `breaker.call_async()`：pybreaker 1.4.1 的实现依赖 tornado
    （`@gen.coroutine`），而本仓库不装 tornado，直接调用会 `NameError: gen`；
    这里改用它的状态机原语（`state._handle_success()` / `_handle_error()`）自己
    驱动，语义与同步 `call()` 一致（失败计数、半开试探、打开后快速失败）。
    """
    try:
        _async_ready_state(breaker)
    except CircuitOpenError:
        raise
    except pybreaker.CircuitBreakerError as exc:
        raise CircuitOpenError(breaker.name or "unknown") from exc

    try:
        result = await func(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 — 需要计数后才向上抛
        try:
            breaker.state._handle_error(exc)
        except pybreaker.CircuitBreakerError as cb_exc:
            raise CircuitOpenError(breaker.name or "unknown") from cb_exc
        raise
    breaker.state._handle_success()
    return result


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


# ─────────────────────── FR-21 熔断状态导出（T088 供指标采集）───────────────────────

CIRCUIT_STATE_CLOSED = "closed"
CIRCUIT_STATE_OPEN = "open"
CIRCUIT_STATE_HALF_OPEN = "half_open"
CIRCUIT_STATE_LABELS = (CIRCUIT_STATE_CLOSED, CIRCUIT_STATE_OPEN, CIRCUIT_STATE_HALF_OPEN)


def breaker_state(breaker: pybreaker.CircuitBreaker) -> str:
    """把 pybreaker 的内部状态映射成稳定标签（指标与告警按它断言）。

    不做映射而直接 `str(breaker.state)` 会把 `<pybreaker.CircuitOpenState object
    at 0x..>` 写进指标标签，标签基数随进程变化，指标直接不可用。
    """
    state = getattr(breaker, "state", None)
    name = type(state).__name__ if state is not None else ""
    if name == "CircuitOpenState":
        return CIRCUIT_STATE_OPEN
    if name == "CircuitHalfOpenState":
        return CIRCUIT_STATE_HALF_OPEN
    return CIRCUIT_STATE_CLOSED


def breaker_failure_count(breaker: pybreaker.CircuitBreaker) -> int:
    """连续失败计数（关闭态下用于观察「离熔断还有多远」）。"""
    # pybreaker 1.4.x 暴露 `fail_counter`；1.0/1.1 用 `_failure_count`。
    count = getattr(breaker, "fail_counter", None)
    if count is None:
        count = getattr(breaker, "_failure_count", 0)
    return int(count or 0)


class BreakerRegistry:
    """进程内熔断器登记表：每依赖一个 breaker，供指标采集与测试注入。"""

    def __init__(self) -> None:
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {}

    def get_or_create(
        self,
        dependency: str,
        *,
        fail_max: int = BREAKER_FAIL_MAX_DEFAULT,
        reset_timeout: float = BREAKER_RESET_TIMEOUT_DEFAULT,
        success_threshold: int = BREAKER_SUCCESS_THRESHOLD_DEFAULT,
        exclude: Iterable[Any] | None = None,
    ) -> pybreaker.CircuitBreaker:
        if dependency not in self._breakers:
            self._breakers[dependency] = make_breaker(
                dependency,
                fail_max=fail_max,
                reset_timeout=reset_timeout,
                success_threshold=success_threshold,
                exclude=exclude,
            )
        return self._breakers[dependency]

    def get(self, dependency: str) -> pybreaker.CircuitBreaker | None:
        return self._breakers.get(dependency)

    def names(self) -> list[str]:
        return sorted(self._breakers)

    def items(self) -> list[tuple[str, pybreaker.CircuitBreaker]]:
        return sorted(self._breakers.items())

    def reset(self) -> None:
        """仅测试使用：清空登记表（避免用例之间共享熔断状态）。"""
        self._breakers.clear()


default_breaker_registry = BreakerRegistry()


# ─────────────────────── FR-25 限流（T085）───────────────────────


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str = ""
    retry_after_seconds: float = 0.0
    limit: float = 0.0


class RateLimiter:
    """租户级令牌桶 + 并发连接上限（进程内实现）。

    为什么是进程内：部署形态是单机 Compose（024 Assumptions 已定），多副本时
    每副本各自计数即「总量 = 副本数 × 单副本限额」，这是需要如实说明的口径，
    而不是假装有跨副本精确限流。跨副本精确限流依赖 Redis 计数，属后续特性。
    """

    def __init__(
        self,
        *,
        qps: float = 20.0,
        burst: int | None = None,
        max_concurrent: int = 100,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if qps <= 0:
            raise ValueError("qps must be > 0")
        self.qps = float(qps)
        self.burst = int(burst if burst is not None else max(1, int(qps)))
        self.max_concurrent = int(max_concurrent)
        self._clock = clock
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}
        self._inflight: dict[str, int] = {}

    def _refill(self, key: str) -> float:
        now = self._clock()
        last = self._updated.get(key, now)
        tokens = self._tokens.get(key, float(self.burst))
        tokens = min(float(self.burst), tokens + (now - last) * self.qps)
        self._tokens[key] = tokens
        self._updated[key] = now
        return tokens

    def acquire(self, key: str) -> RateLimitDecision:
        """取一个令牌并占用一个并发槽；被拒时不改变任何计数。"""
        if self._inflight.get(key, 0) >= self.max_concurrent:
            return RateLimitDecision(
                allowed=False,
                reason="concurrency",
                retry_after_seconds=0.0,
                limit=float(self.max_concurrent),
            )

        tokens = self._refill(key)
        if tokens < 1.0:
            deficit = 1.0 - tokens
            return RateLimitDecision(
                allowed=False,
                reason="qps",
                retry_after_seconds=max(0.0, deficit / self.qps),
                limit=self.qps,
            )

        self._tokens[key] = tokens - 1.0
        self._inflight[key] = self._inflight.get(key, 0) + 1
        return RateLimitDecision(allowed=True, limit=self.qps)

    def release(self, key: str) -> None:
        current = self._inflight.get(key, 0)
        if current <= 1:
            self._inflight.pop(key, None)
        else:
            self._inflight[key] = current - 1

    def inflight(self, key: str) -> int:
        return self._inflight.get(key, 0)

    def forget(self, key: str) -> None:
        self._tokens.pop(key, None)
        self._updated.pop(key, None)
        self._inflight.pop(key, None)


# ─────────────────────── FR-25 背压（T086）───────────────────────

BACKPRESSURE_QUEUE_DEPTH_DEFAULT = 1000


class BackpressureError(RuntimeError):
    """在途请求数超过队列深度上限 —— 快速拒绝（429），不要排进无界队列。"""

    retry_after_seconds = 1.0

    def __init__(self, name: str, depth: int, limit: int) -> None:
        super().__init__(f"backpressure limit reached for {name}: {depth}/{limit}")
        self.name = name
        self.depth = depth
        self.limit = limit


class BackpressureGuard:
    """在途请求计数守卫：深度达到上限即拒绝新请求（有界队列思想）。

    与限流的区别：限流按**速率**（同一租户每秒多少次），背压按**在途量**
    （整体积压多少）。只做限流不做背压时，上游持续超量仍会把队列堆到 OOM。
    """

    def __init__(
        self,
        name: str = "default",
        *,
        max_depth: int = BACKPRESSURE_QUEUE_DEPTH_DEFAULT,
    ) -> None:
        if max_depth <= 0:
            raise ValueError("max_depth must be > 0")
        self.name = name
        self.max_depth = int(max_depth)
        self._depth = 0

    @property
    def depth(self) -> int:
        return self._depth

    def enter(self) -> None:
        if self._depth >= self.max_depth:
            raise BackpressureError(self.name, self._depth, self.max_depth)
        self._depth += 1

    def try_enter(self) -> bool:
        """非异常式入口（ASGI 中间件用）：成功返回 True 并占位，超限返回 False。

        中间件里用返回值判断比 try/except 更清晰，也避免中间件需要导入本模块的
        异常类型（vendored 副本不互相 import，保持零耦合）。
        """
        if self._depth >= self.max_depth:
            return False
        self._depth += 1
        return True

    def leave(self) -> None:
        if self._depth > 0:
            self._depth -= 1

    def reset(self) -> None:
        self._depth = 0
