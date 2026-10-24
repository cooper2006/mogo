"""026 T002 — 性能基线采集骨架。

占位模块，Phase 2（US1）填充实现。
目标：基于 `spans.py` 的 span 数据聚合 P50/P95/P99 延迟 + RPS/TPS 吞吐，
落库 `perf_baselines` collection。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PerfBaselineRecord:
    """单次基线采集结果。"""
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
    """性能基线采集器占位。

    Phase 2 实现时：
    - 从 `spans.py` 的 span 数据聚合延迟分位数
    - 按并发级别（1/10/50/100）记录吞吐
    - 落库 `perf_baselines` collection
    """
    records: List[PerfBaselineRecord] = field(default_factory=list)

    async def collect(self, spans: List[Dict[str, Any]]) -> List[PerfBaselineRecord]:
        """占位：返回空列表。"""
        return []

    async def persist(self, record: PerfBaselineRecord) -> None:
        """占位：无操作。"""

    async def query(self, endpoint: Optional[str] = None) -> List[PerfBaselineRecord]:
        """占位：返回空列表。"""
        return []
