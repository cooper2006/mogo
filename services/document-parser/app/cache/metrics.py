"""026 T030 — 缓存命中率监控（FR-18）。

把 CacheManager 的命中率等指标落库（写入 Kafka/时序存储或暴露到
``/debug/runtime-kpi`` 由 008 驾驶舱消费），命中率 < 80% 告警。

用法::

    reporter = CacheMetricsReporter(cache_manager, kpi_store=runtime_kpi_store)
    await reporter.report()          # 落库 + 检查告警阈值
    reporter.threshold = 0.8         # 可配

本模块自包含（stdlib + typing），便于 vendored 副本独立校验。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_HIT_RATE_MIN = 0.8  # 命中率下限（Clarify 定值）
DEFAULT_REPORT_INTERVAL_SECONDS = 30.0
KPI_CACHE_HIT_RATE_KEY = "cache_hit_rate"
KPI_CACHE_STATS_KEY = "cache_stats"


class CacheMetricsReporter:
    """缓存指标采集器：命中率/请求数/backend/namespace，落库 + 阈值告警。"""

    def __init__(
        self,
        manager: Any,
        *,
        kpi_store: Optional[Any] = None,
        hit_rate_min: float = DEFAULT_HIT_RATE_MIN,
        interval_seconds: float = DEFAULT_REPORT_INTERVAL_SECONDS,
    ) -> None:
        self._manager = manager
        self._kpi_store = kpi_store
        self.hit_rate_min = float(hit_rate_min)
        self.interval_seconds = float(interval_seconds)
        self._last_report = 0.0
        self._alerts = 0

    @property
    def alerts(self) -> int:
        return self._alerts

    def should_report(self, *, now: Optional[float] = None) -> bool:
        """距上次上报是否已过 interval（避免高频刷库）。"""
        now = time.monotonic() if now is None else now
        return (now - self._last_report) >= self.interval_seconds

    def collect(self) -> Dict[str, Any]:
        """采集一次指标快照（不落库）。"""
        stats = self._manager.stats()
        hit_rate = float(stats.get("hit_rate") or 0.0)
        return {
            "namespace": self._manager.namespace,
            "backend": stats.get("backend"),
            "hit_rate": hit_rate,
            "hit_rate_min": self.hit_rate_min,
            "breached": hit_rate < self.hit_rate_min,
            "hits": int(stats.get("hits") or 0),
            "misses": int(stats.get("misses") or 0),
            "requests": int(stats.get("requests") or 0),
            "writes": int(stats.get("writes") or 0),
            "evictions": int(stats.get("evictions") or 0),
            "collected_at": time.time(),
        }

    async def report(self, *, now: Optional[float] = None) -> Dict[str, Any]:
        """采集并把指标落库（kpi_store），命中率低于阈值时告警。返回快照。"""
        snapshot = self.collect()
        self._last_report = time.monotonic() if now is None else now
        # 落库到 kpi_store（供 /debug/runtime-kpi 与 008 驾驶舱消费）
        if self._kpi_store is not None:
            try:
                set_value = self._kpi_store.set_value
                if hasattr(set_value, "__call__"):
                    result = set_value(KPI_CACHE_HIT_RATE_KEY, snapshot["hit_rate"])
                    if hasattr(result, "__await__"):
                        await result
                set_stats = self._kpi_store.set_value
                if hasattr(set_stats, "__call__"):
                    result = set_stats(KPI_CACHE_STATS_KEY, snapshot)
                    if hasattr(result, "__await__"):
                        await result
            except Exception:
                logger.warning(
                    "cache metrics persist failed",
                    extra={"event": "cache.metrics_persist_failed"},
                )
        # 阈值告警
        if snapshot["breached"]:
            self._alerts += 1
            logger.error(
                "cache hit rate below threshold",
                extra={
                    "event": "cache.hit_rate_low",
                    "cache_namespace": snapshot["namespace"],
                    "hit_rate": snapshot["hit_rate"],
                    "hit_rate_min": snapshot["hit_rate_min"],
                },
            )
        else:
            logger.info(
                "cache hit rate ok",
                extra={
                    "event": "cache.hit_rate_ok",
                    "cache_namespace": snapshot["namespace"],
                    "hit_rate": snapshot["hit_rate"],
                },
            )
        return snapshot


__all__ = ["CacheMetricsReporter", "DEFAULT_HIT_RATE_MIN", "DEFAULT_REPORT_INTERVAL_SECONDS"]