"""023 T005 — SLO 数据结构与错误预算计算（权威源）。

vendored 副本纪律见 `observability_base.py` 头注。

口径（spec Clarify 决策 2026-10-24）：
- OQ-6：可用性 99.9%（30 天窗口）、请求延迟 P99 < 3s、LLM 调用错误率 < 1%。
- burn rate 告警：两组窗口——快档 1h/6h（阈值 14.4 与 6，page 级）、
  慢档 6h/3d（阈值 6 与 2，ticket 级）——Google SRE 多窗口多燃速标准组合。
- 错误预算 = (1 - SLO) × 窗口内事件总数；预算耗尽（remaining ≤ 0）触发 FR-15 告警。

纯计算模块：无 IO、无服务私有 import，可被三服务 vendor 与单测直接覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SLOKind(str, Enum):
    AVAILABILITY = "availability"      # good_events / total_events ≥ target
    LATENCY = "latency"                # fast_count / total_count ≥ target（P99<3s 折算）
    ERROR_RATE = "error_rate"          # 反向：error/total ≤ (1 - target)


@dataclass(frozen=True)
class SLOSpec:
    name: str
    kind: SLOKind
    target: float                      # 0~1，如 0.999
    window_days: float = 30.0
    description: str = ""

    def __post_init__(self) -> None:
        if not (0.0 < self.target < 1.0):
            raise ValueError(f"SLO target must be in (0,1): {self.name}={self.target}")
        if self.window_days <= 0:
            raise ValueError("window_days must be positive")

    @property
    def budget_ratio(self) -> float:
        """允许的坏事件比例 = 1 - target。"""
        return 1.0 - self.target


#: 首期三件套（FR-14，决策 OQ-6）
DEFAULT_SLOS: tuple[SLOSpec, ...] = (
    SLOSpec(
        name="availability_30d",
        kind=SLOKind.AVAILABILITY,
        target=0.999,
        window_days=30.0,
        description="非 5xx 响应占比 ≥ 99.9%（30d 滚动）",
    ),
    SLOSpec(
        name="latency_p99_30d",
        kind=SLOKind.LATENCY,
        target=0.99,
        window_days=30.0,
        description="P99 < 3s ⇔ 延迟 ≤3s 的请求占比 ≥ 99%",
    ),
    SLOSpec(
        name="llm_error_rate_30d",
        kind=SLOKind.ERROR_RATE,
        target=0.99,
        window_days=30.0,
        description="LLM 调用错误率 < 1% ⇔ 成功率 ≥ 99%",
    ),
)


@dataclass(frozen=True)
class ErrorBudget:
    spec: SLOSpec
    total_events: float
    bad_events: float

    @property
    def budget_total(self) -> float:
        return self.total_events * self.spec.budget_ratio

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self.budget_total - self.bad_events)

    @property
    def budget_consumed_ratio(self) -> float:
        if self.budget_total <= 0:
            return 1.0 if self.bad_events > 0 else 0.0
        return min(1.0, self.bad_events / self.budget_total)

    @property
    def exhausted(self) -> bool:
        return self.bad_events >= self.budget_total

    @property
    def observed_ratio(self) -> float | None:
        """实测合规比例（good/total）；total=0 时无观测值。"""
        if self.total_events <= 0:
            return None
        return (self.total_events - self.bad_events) / self.total_events


@dataclass(frozen=True)
class BurnRate:
    """burn rate = 观测坏事件速率 ÷ 预算允许速率。1.0 = 恰好按预算消耗。"""

    short_window_seconds: float
    long_window_seconds: float
    short_bad: float
    short_total: float
    long_bad: float
    long_total: float
    budget_ratio: float

    def _rate(self, bad: float, total: float) -> float:
        return bad / total if total > 0 else 0.0

    @property
    def short_rate(self) -> float:
        base = self._rate(self.short_bad, self.short_total)
        return base / self.budget_ratio if self.budget_ratio > 0 else float("inf")

    @property
    def long_rate(self) -> float:
        base = self._rate(self.long_bad, self.long_total)
        return base / self.budget_ratio if self.budget_ratio > 0 else float("inf")


class BurnLevel(Enum):
    NONE = "none"          # 未达告警线
    PAGE_FAST = "page_fast"      # 快档双窗口同超（P0 立即页人）
    PAGE_SLOW = "page_slow"      # 快档长期窗超（P0/P1，页人但可稍缓）
    TICKET = "ticket"            # 慢档双窗超（工单，不页人）


#: Google SRE 多窗口多燃速标准四表（决策 OQ-6 burn 窗口 1h/6h + 6h/3d）
BURN_RULES: tuple[tuple[float, float, float, BurnLevel], ...] = (
    # (short_seconds, long_seconds, threshold, level) 按优先级排列
    (3600.0, 21600.0, 14.4, BurnLevel.PAGE_FAST),    # 1h/6h ×14.4
    (3600.0, 21600.0, 6.0, BurnLevel.PAGE_SLOW),     # 1h/6h ×6
    (21600.0, 259200.0, 6.0, BurnLevel.TICKET),      # 6h/3d ×6
    (21600.0, 259200.0, 2.0, BurnLevel.NONE),        # 6h/3d ×2 仅记录不告警
)


def evaluate_burn(burn: BurnRate) -> BurnLevel:
    """按 BURN_RULES 顺序取第一个同时满足双窗阈值的等级。"""
    for short_s, long_s, threshold, level in BURN_RULES:
        if (
            burn.short_window_seconds == short_s
            and burn.long_window_seconds == long_s
        ):
            if burn.short_rate >= threshold and burn.long_rate >= threshold:
                return level
    return BurnLevel.NONE


def compute_error_budget(spec: SLOSpec, total_events: float, bad_events: float) -> ErrorBudget:
    if bad_events < 0 or total_events < 0:
        raise ValueError("event counts must be non-negative")
    if bad_events > total_events:
        raise ValueError(f"bad_events > total_events: {bad_events}>{total_events}")
    return ErrorBudget(spec=spec, total_events=total_events, bad_events=bad_events)
