"""026 T009 — 性能预算检查器（真实实现）。

读 `benchmarks/perf_baselines/baselines.yaml`（026 T010，Clarify 定值），
与运行时 KPI 采集的延迟/吞吐基线比对，超阈值 → `alert()`（structlog 告警，
可挂接 perf_alerts 持久化）。

与 `perf_baseline.py` 的分工：
* `perf_baseline.py` — 从请求 span 聚合基线（P50/P95/P99/RPS/TPS）
* `perf_budget.py`   — 把基线与预算阈值比对，判 breach
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PerfBudgetThreshold:
    """单项性能预算阈值。"""
    endpoint: str
    metric: str  # p50_ms / p95_ms / p99_ms / rps / tps / bundle_kb / ...
    max_value: float
    current_value: float = 0.0
    breached: bool = False
    # 服务名（baselines.yaml 按服务分组；跨服务配置时为空表示全局项）
    service: str = ""


@dataclass
class PerfBudgetChecker:
    """性能预算检查器：加载阈值 → 与基线比对 → 告警。"""

    thresholds: List[PerfBudgetThreshold] = field(default_factory=list)
    # 非端点级阈值（数据库连接池 / 缓存命中 / 并发 / 熔断 / 回归）
    service_name: str = "chat-api"
    config_path: Optional[str] = None
    _global_thresholds: Dict[str, Any] = field(default_factory=dict)

    async def load_thresholds(self, config_path: str) -> None:
        """加载 `baselines.yaml`，把本服务相关的阈值装配进 `thresholds`。"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"性能基线配置不存在: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.config_path = config_path
        self._global_thresholds = {
            "frontend": data.get("frontend", {}),
            "cache": data.get("cache", {}),
            "database": data.get("database", {}),
            "concurrency": data.get("concurrency", {}),
            "circuit_breaker": data.get("circuit_breaker", {}),
            "regression": data.get("regression", {}),
        }
        self.thresholds = []
        services = data.get("services", {})
        # 本服务相关阈值
        service_cfg = services.get(self.service_name, {})
        defaults = service_cfg.get("defaults", {}) or {}
        default_p95 = float(defaults.get("p95_max_ms", 0.0))
        latency = service_cfg.get("latency", {}) or {}
        for endpoint, cfg in latency.items():
            cfg = cfg or {}
            self.thresholds.append(
                PerfBudgetThreshold(
                    endpoint=endpoint,
                    metric="p95_ms",
                    max_value=float(cfg.get("p95_max_ms", default_p95)),
                    service=self.service_name,
                )
            )
        throughput = service_cfg.get("throughput", {}) or {}
        max_rps = throughput.get("max_rps_per_instance")
        if max_rps is not None:
            self.thresholds.append(
                PerfBudgetThreshold(
                    endpoint="__service__",
                    metric="rps",
                    max_value=float(max_rps),
                    service=self.service_name,
                )
            )

    def threshold_for(self, endpoint: str, metric: str = "p95_ms") -> Optional[PerfBudgetThreshold]:
        """按端点精确匹配；无则按服务级 defaults 的 p95_ms 兜底。"""
        for t in self.thresholds:
            if t.endpoint == endpoint and t.metric == metric:
                return t
        # 兜底：本服务已列出的端点里，取 defaults 口径（若有）
        defaults = self.global_value("regression", {})
        return None

    def global_value(self, section: str, key: str) -> Any:
        return (self._global_thresholds.get(section) or {}).get(key)

    async def check(self, baseline: Dict[str, Any]) -> List[PerfBudgetThreshold]:
        """与基线比对。

        `baseline` 形状（`PerfBaselineCollector.query` / `kpi_store.perf_summary`）：
        ``{endpoint: {"p50": .., "p95": .., "p99": .., "count": ..}}`` 或
        ``{"endpoint_percentiles": {...}, "throughput": {...}}``。
        返回所有被 breach 的阈值（未 breach 的保留 current_value，breached=False）。
        """
        percents = baseline.get("endpoint_percentiles", baseline)
        for t in self.thresholds:
            t.breached = False
            if t.metric == "rps" and t.endpoint == "__service__":
                tp = baseline.get("throughput", {})
                cur = float(tp.get("rps_total", 0.0))
                t.current_value = cur
                t.breached = cur > t.max_value
                continue
            if t.metric != "p95_ms":
                continue
            stats = percents.get(t.endpoint)
            if not isinstance(stats, dict):
                continue
            cur = float(stats.get("p95", 0.0))
            t.current_value = cur
            t.breached = cur > t.max_value
        return [t for t in self.thresholds if t.breached]

    async def alert(self, threshold: PerfBudgetThreshold) -> None:
        """记录性能预算告警（structlog；可替换为持久化写入 perf_alerts）。"""
        logger.error(
            "perf_budget_breached",
            extra={
                "service": threshold.service or self.service_name,
                "endpoint": threshold.endpoint,
                "metric": threshold.metric,
                "max_value": threshold.max_value,
                "current_value": threshold.current_value,
            },
        )

    # ── 026 T009: 前端包体积预算检查 ────────────────────────────────────────────

    async def check_frontend_bundle(
        self, actual_kb: Dict[str, float]
    ) -> List[PerfBudgetThreshold]:
        """对照 baselines.yaml 的 ``frontend.*.bundle_gzip_max_kb`` 检查首屏体积。"""
        frontend = self._global_thresholds.get("frontend", {}) or {}
        breached: List[PerfBudgetThreshold] = []
        for svc, cfg in frontend.items():
            if svc == "lcp_max_s" or not isinstance(cfg, dict):
                continue
            limit = float(cfg.get("bundle_gzip_max_kb", 0.0))
            actual = float(actual_kb.get(svc, 0.0))
            threshold = PerfBudgetThreshold(
                endpoint="__frontend__",
                metric="bundle_kb",
                max_value=limit,
                current_value=actual,
                breached=actual > limit,
                service=svc,
            )
            if threshold.breached:
                breached.append(threshold)
        return breached

    # ── 026 T011: 回归判定（FR-5）────────────────────────────────────────────────

    async def check_regression(
        self,
        new_baseline: Dict[str, Any],
        historical_baseline: Dict[str, Any],
        *,
        ratio: Optional[float] = None,
    ) -> List[PerfBudgetThreshold]:
        """新构建基线 vs 历史基线，P95 劣化超过阈值判回归。

        ``baseline`` 形状：``{endpoint: {"p95": ms}}``。
        阈值默认取 ``regression.p95_regression_ratio``（=1.2，即 +20%）。
        返回所有回归项；未回归的端点不会出现在结果里。
        """
        if ratio is None:
            ratio = float(self.global_value("regression", "p95_regression_ratio") or 1.2)
        new_pct = new_baseline.get("endpoint_percentiles", new_baseline)
        hist_pct = historical_baseline.get("endpoint_percentiles", historical_baseline)
        regressions: List[PerfBudgetThreshold] = []
        for endpoint, stats in new_pct.items():
            if not isinstance(stats, dict):
                continue
            new_p95 = float(stats.get("p95", 0.0))
            hist_stats = hist_pct.get(endpoint)
            if not isinstance(hist_stats, dict):
                continue  # 历史无该端点 → 无从比较
            hist_p95 = float(hist_stats.get("p95", 0.0))
            if hist_p95 <= 0:
                continue
            actual_ratio = new_p95 / hist_p95
            if actual_ratio > ratio:
                regressions.append(
                    PerfBudgetThreshold(
                        endpoint=endpoint,
                        metric="p95_regression",
                        max_value=ratio,
                        current_value=actual_ratio,
                        breached=True,
                        service=self.service_name,
                    )
                )
        return regressions