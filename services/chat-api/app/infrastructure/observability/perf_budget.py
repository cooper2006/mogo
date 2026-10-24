"""026 T003 — 性能预算检查骨架。

占位模块，Phase 2（US1）填充实现。
目标：读 `deploy/config/performance.yaml` 阈值配置，与基线对比，
超阈值告警写入 `perf_alerts` collection。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PerfBudgetThreshold:
    """单项性能预算阈值。"""
    endpoint: str
    metric: str  # p50_ms / p95_ms / p99_ms / rps / tps
    max_value: float
    current_value: float = 0.0
    breached: bool = False


@dataclass
class PerfBudgetChecker:
    """性能预算检查器占位。

    Phase 2 实现时：
    - 从 `deploy/config/performance.yaml` 加载阈值配置
    - 与 `perf_baseline.py` 的基线数据对比
    - 超阈值写入 `perf_alerts` collection
    """
    thresholds: List[PerfBudgetThreshold] = field(default_factory=list)

    async def load_thresholds(self, config_path: str) -> None:
        """占位：无操作。"""

    async def check(self, baseline: Dict[str, Any]) -> List[PerfBudgetThreshold]:
        """占位：返回空列表。"""
        return []

    async def alert(self, threshold: PerfBudgetThreshold) -> None:
        """占位：无操作。"""
