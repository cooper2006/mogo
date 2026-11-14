"""026 T006/T007 — 性能基线采集器（真实实现）。

数据源：`spans.py` 的已完成 span 缓冲区（`drain_completed_spans`）+ KPI 中间件
采集的端点级延迟（可选合并）。聚合 P50/P95/P99 延迟与 RPS/TPS 吞吐，
按 `spec.md` 要求分档记录。

`persist` 默认写入内存 `records`（供 query 与告警用）；如需落 Mongo
`perf_baselines`，可在 `persist` 里注入持久化回调（`on_persist`）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.infrastructure.observability.spans import drain_completed_spans


def _percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = int(round(q * (n - 1)))
    return float(sorted_values[min(max(idx, 0), n - 1)])


@dataclass
class PerfBaselineRecord:
    """单次基线采集结果（按 span.name / endpoint 聚合）。"""
    endpoint: str
    method: str
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    rps: float = 0.0
    tps: float = 0.0
    sample_count: int = 0
    collected_at: float = 0.0


@dataclass
class PerfBaselineCollector:
    """性能基线采集器。

    `window_seconds`：吞吐统计窗口；`concurrency_buckets`：并发分档标签。
    """

    records: List[PerfBaselineRecord] = field(default_factory=list)
    window_seconds: int = 60
    concurrency_buckets: tuple = (1, 10, 50, 100)
    on_persist: Optional[Callable[[PerfBaselineRecord], None]] = None

    async def collect(self, spans: List[Dict[str, Any]]) -> List[PerfBaselineRecord]:
        """从已完成 span 记录聚合延迟分位数与吞吐。

        span 记录形状：``{name, duration_ms, finished_at, error, ...}``。
        """
        if not spans:
            return []
        by_name: Dict[str, List[float]] = {}
        finished: List[float] = []
        for span in spans:
            name = str(span.get("name") or "")
            dur = float(span.get("duration_ms", 0.0))
            by_name.setdefault(name, []).append(dur)
            ft = float(span.get("finished_at", time.time()))
            finished.append(ft)
        now = time.time()
        window = self.window_seconds
        recent = [ft for ft in finished if ft >= now - window]
        rate = len(recent) / window if recent else 0.0
        out: List[PerfBaselineRecord] = []
        for name, durs in by_name.items():
            ordered = sorted(durs)
            out.append(
                PerfBaselineRecord(
                    endpoint=name,
                    method="span",
                    p50_ms=_percentile(ordered, 0.50),
                    p95_ms=_percentile(ordered, 0.95),
                    p99_ms=_percentile(ordered, 0.99),
                    rps=rate,
                    tps=rate,
                    sample_count=len(ordered),
                    collected_at=now,
                )
            )
        out.sort(key=lambda r: r.sample_count, reverse=True)
        return out

    async def collect_from_span_buffer(self) -> List[PerfBaselineRecord]:
        """从 `spans.py` 的已完成 span 缓冲区采集（并清空缓冲区）。"""
        spans = drain_completed_spans()
        if not spans:
            return []
        return await self.collect(spans)

    async def persist(self, record: PerfBaselineRecord) -> None:
        """持久化单条基线记录（默认内存；可注入 on_persist 落库）。"""
        # 去重：同 endpoint+method 保留最新一条
        self.records = [r for r in self.records if not (r.endpoint == record.endpoint and r.method == record.method)]
        self.records.append(record)
        if self.on_persist is not None:
            self.on_persist(record)

    async def query(self, endpoint: Optional[str] = None) -> List[PerfBaselineRecord]:
        """按端点查询最近基线记录；endpoint 为空返回全部。"""
        if endpoint:
            return [r for r in self.records if r.endpoint == endpoint]
        return list(self.records)