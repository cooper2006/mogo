"""026 T014/T015/T016/T017/T019/T022 — 数据库性能守护（chat-api，Mongo 后端）。

职责分工（对应 FR-6/FR-9/FR-10/FR-11/FR-12 与 baselines.yaml database 段）：
* T014 连接池参数：`pool_kwargs()` 返回可传给 ``AsyncIOMotorClient`` 的参数；
  `PoolLeakTracker` 登记借出/归还，> 90s 未释放记泄漏告警。
* T015 慢查询登记：`SlowQueryRegistry` 记录超阈值（默认 100ms）查询，可落
  `slow_queries`。
* T016 查询超时：`with_query_timeout()` 包装 find/aggregate，默认 `max_time_ms`=5000。
* T017 查询熔断（错误率口径）：`ErrorRateWindow` 滚动 30s 错误率 > 50% 判熔断，
  `guarded_query()` 熔断打开时快速失败。与 `core.resilience.mongo_breaker`
  （pybreaker 计数式，023 FR-21）互补：本模块是「错误率前置门」。
* T019 执行计划分析：`explain_and_store()` 跑 ``explain("executionStats")`` 落
  `query_plans`。
* T022 连接池监控：`pool_utilization_snapshot()` 读 `core.resilience` 登记的
  PoolRegistry，输出利用率（峰值 ≤ 0.8）。

本模块只依赖标准库 + `app.core.config`/`app.core.resilience`，便于单测。
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ───────────────────────── T014 连接池（Clarify 定值）─────────────────────────
DEFAULT_MAX_POOL_SIZE = 100
DEFAULT_MIN_POOL_SIZE = 10
DEFAULT_MAX_IDLE_MS = 30000
LEAK_WARN_MS = 90000
DEFAULT_MAX_TIME_MS = 5000
SLOW_QUERY_THRESHOLD_MS = 100
ERROR_RATE_WINDOW_SECONDS = 30
ERROR_RATE_MAX = 0.5


def pool_kwargs(settings: Any = None) -> Dict[str, int]:
    """返回传给 ``AsyncIOMotorClient`` 的连接池参数（T014）。

    环境变量可覆盖：``MONGODB_MAX_POOL_SIZE`` / ``MONGODB_MIN_POOL_SIZE`` /
    ``MONGODB_MAX_IDLE_MS``。
    """
    import os

    settings = settings or get_settings()

    def _int(name: str, default: int) -> int:
        raw = os.getenv(name, "")
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    return {
        "maxPoolSize": _int("MONGODB_MAX_POOL_SIZE", DEFAULT_MAX_POOL_SIZE),
        "minPoolSize": _int("MONGODB_MIN_POOL_SIZE", DEFAULT_MIN_POOL_SIZE),
        "maxIdleTimeMS": _int("MONGODB_MAX_IDLE_MS", DEFAULT_MAX_IDLE_MS),
    }


@dataclass
class PoolLeakTracker:
    """连接泄漏检测：> LEAK_WARN_MS 未归还记泄漏告警。

    与查询级 wrapper（`GuardedCollection`）配合：进入查询时 `checkout(token)`，
    完成时 `checkin(token)`；`leaked()` 返回所有超时未归还的 token。
    """

    warn_ms: int = LEAK_WARN_MS
    _borrowed: Dict[str, float] = field(default_factory=dict)

    def checkout(self, token: str, now: Optional[float] = None) -> None:
        self._borrowed[token] = now if now is not None else time.monotonic()

    def checkin(self, token: str) -> Optional[float]:
        return self._borrowed.pop(token, None)

    def leaked(self, now: Optional[float] = None) -> List[str]:
        now = now if now is not None else time.monotonic()
        out = [t for t, started in self._borrowed.items() if (now - started) * 1000 > self.warn_ms]
        for token in out:
            logger.warning(
                "db_connection_leak",
                extra={"token": token, "warn_ms": self.warn_ms},
            )
        return out

    def borrowed_count(self) -> int:
        return len(self._borrowed)


# ───────────────────────── T015 慢查询登记 ─────────────────────────
@dataclass
class SlowQueryRegistry:
    """慢查询登记：超阈值（默认 100ms）记录，可被周期任务落 `slow_queries`。"""

    threshold_ms: float = SLOW_QUERY_THRESHOLD_MS
    records: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, command: str, namespace: str, duration_ms: float, **extra: Any) -> bool:
        """若 `duration_ms` 超阈值则登记并返回 True。"""
        if duration_ms < self.threshold_ms:
            return False
        self.records.append(
            {
                "command": command,
                "namespace": namespace,
                "duration_ms": duration_ms,
                "threshold_ms": self.threshold_ms,
                "at": time.time(),
                **extra,
            }
        )
        logger.warning(
            "db_slow_query",
            extra={"command": command, "namespace": namespace, "duration_ms": duration_ms, "threshold_ms": self.threshold_ms},
        )
        return True

    def drain(self) -> List[Dict[str, Any]]:
        out = list(self.records)
        self.records.clear()
        return out

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self.records)[-limit:]


# ───────────────────────── T017 滚动错误率熔断 ─────────────────────────
@dataclass
class ErrorRateWindow:
    """滚动 30s 错误率熔断（FR-9：错误率 > 50% 触发熔断）。"""

    window_seconds: float = ERROR_RATE_WINDOW_SECONDS
    error_rate_max: float = ERROR_RATE_MAX
    _events: Deque[tuple] = field(default_factory=lambda: deque())

    def record(self, ok: bool, now: Optional[float] = None) -> None:
        now = now if now is not None else time.monotonic()
        self._events.append((now, bool(ok)))
        self._prune(now)

    def rate(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.monotonic()
        self._prune(now)
        total = len(self._events)
        if total == 0:
            return 0.0
        errors = sum(1 for _, ok in self._events if not ok)
        return errors / total

    def tripped(self, now: Optional[float] = None) -> bool:
        return self.rate(now) > self.error_rate_max

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()


# ───────────────────────── T016/T017 查询包装 ─────────────────────────
class GuardedCollection:
    """包装 motor collection，自动加查询超时 + 慢查询登记 + 错误率熔断。

    用法：``GuardedCollection(db["chat_messages"], slow=..., breaker=...)``，
    之后 ``await gc.find(query).to_list(...)`` 与原生 motor API 一致，
    只是 ``find``/``aggregate`` 会带默认 ``max_time_ms``，并统计耗时。
    """

    def __init__(
        self,
        collection: Any,
        *,
        default_max_time_ms: int = DEFAULT_MAX_TIME_MS,
        slow_registry: Optional[SlowQueryRegistry] = None,
        breaker: Optional[ErrorRateWindow] = None,
        leak_tracker: Optional[PoolLeakTracker] = None,
    ) -> None:
        self._collection = collection
        self.default_max_time_ms = default_max_time_ms
        self.slow = slow_registry
        self.breaker = breaker
        self.leak = leak_tracker

    @property
    def name(self) -> str:
        return getattr(self._collection, "name", "")

    async def find(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("max_time_ms", kwargs.pop("max_time_ms", self.default_max_time_ms))
        return await self._guarded("find", *args, **kwargs)

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("max_time_ms", kwargs.pop("max_time_ms", self.default_max_time_ms))
        return await self._guarded("find_one", *args, **kwargs)

    async def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("max_time_ms", kwargs.pop("max_time_ms", self.default_max_time_ms))
        return await self._guarded("aggregate", *args, **kwargs)

    async def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("max_time_ms", kwargs.pop("max_time_ms", self.default_max_time_ms))
        return await self._guarded("count_documents", *args, **kwargs)

    async def _guarded(self, command: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self._collection, command)
        if self.leak is not None:
            token = f"{command}:{id(self)}:{time.monotonic_ns()}"
            self.leak.checkout(token)
        started = time.monotonic()
        ok = True
        try:
            return await method(*args, **kwargs)
        except Exception:
            ok = False
            raise
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            if self.leak is not None:
                self.leak.checkin(token)  # type: ignore[name-defined]  # noqa: F821
            if self.slow is not None:
                self.slow.record(command, self.name, duration_ms)
            if self.breaker is not None:
                self.breaker.record(ok)


async def guarded_query(
    breaker: ErrorRateWindow,
    operation_name: str,
    coro_fn: Any,
    *args: Any,
    fallback: Any = None,
    **kwargs: Any,
) -> Any:
    """熔断打开时快速失败（FR-9），否则执行协程；可用 `fallback` 降级。

    `coro_fn` 可以是 coroutine 对象（``db.find(...)`` 的返回值），也可以是
    返回 coroutine 的 callable（``db.find`` 本身）。
    """
    import asyncio

    if breaker.tripped():
        logger.error(
            "db_circuit_open",
            extra={"operation": operation_name, "error_rate": breaker.rate()},
        )
        if fallback is not None:
            result = fallback() if callable(fallback) else fallback
            if asyncio.iscoroutine(result):
                result = await result
            return result
        raise RuntimeError(f"database circuit open: {operation_name}")

    target = coro_fn(*args, **kwargs) if callable(coro_fn) else coro_fn
    try:
        result = await target
        breaker.record(True)
        return result
    except Exception:
        breaker.record(False)
        raise


# ───────────────────────── T019 执行计划分析 ─────────────────────────
async def explain_and_store(
    db: Any,
    collection_name: str,
    query_filter: Dict[str, Any],
    *,
    projection: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    plans_collection: str = "query_plans",
) -> Dict[str, Any]:
    """对关键查询跑 ``explain("executionStats")``，结果落 `query_plans`。

    返回 explain 结果（含 `executionStats` 关键字段摘要），便于索引优化参考。
    """
    collection = db[collection_name]
    cursor = await collection.find(query_filter, projection)
    result = await cursor.explain(verbosity="executionStats")
    stats = ((result or {}).get("executionStats") or {}) if isinstance(result, dict) else {}
    record = {
        "collection": collection_name,
        "query_filter": query_filter,
        "projection": projection,
        "limit": limit,
        "executionStats": {
            "nReturned": stats.get("nReturned"),
            "totalDocsExamined": stats.get("totalDocsExamined"),
            "totalKeysExamined": stats.get("totalKeysExamined"),
            "executionSuccess": stats.get("executionSuccess"),
            "executionTimeMillis": stats.get("executionTimeMillis"),
        },
        "at": time.time(),
    }
    try:
        await db[plans_collection].insert_one(record)
    except Exception as exc:  # 计划存储失败不阻断主查询
        logger.warning("db_explain_store_failed", extra={"collection": collection_name, "error": str(exc)})
    return record


# ───────────────────────── T022 连接池监控 ─────────────────────────
def pool_utilization_snapshot() -> Dict[str, Any]:
    """读 `core.resilience` 登记的池，输出利用率（峰值 ≤ 0.8 目标）。"""
    from app.core import resilience

    out: Dict[str, Any] = {}
    for dep in (resilience.MONGO_DEPENDENCY, resilience.REDIS_DEPENDENCY):
        spec = resilience.pool_spec(dep)
        if spec is None:
            out[dep] = {"registered": False}
            continue
        utilization = spec.utilization()
        out[dep] = {
            "registered": True,
            "max": getattr(spec, "max", None),
            "utilization": utilization,
            "peak_utilization_max": 0.8,
            "breached": (utilization or 0.0) > 0.8,
        }
    return out