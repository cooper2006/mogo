"""Canary rollout + automatic rollback (016 FR-4 / FR-5 / clarify OQ-2 / OQ-3).

* first delivery rolls out **by tenant** (clarify OQ-2);
* automatic rollback triggers when the canary error rate exceeds **20%**
  (configurable, clarify OQ-3);
* a **minimum sample size** guards against small-sample noise (FR-10).

Rollback target is the Skill's **previous published stable version** (FR-13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

DEFAULT_CANARY_ROLLBACK_THRESHOLD = 0.20   # 20% error rate
DEFAULT_MIN_CANARY_SAMPLES = 20


class RolloutState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


class CanaryError(ValueError):
    """Raised for an invalid canary operation."""


@dataclass
class CanaryDecision:
    """Outcome of evaluating a canary's health."""

    state: str
    error_rate: float
    should_rollback: bool
    reason: str = ""
    sample_sufficient: bool = True


@dataclass
class Rollout:
    """A canary rollout of one Skill version to a set of tenants."""

    skill_id: str
    version: int
    stable_version: int = 0                 # the version to roll back to
    target_tenants: list[str] = field(default_factory=list)
    state: str = RolloutState.PENDING.value
    error_count: int = 0
    call_count: int = 0

    def __post_init__(self) -> None:
        if not str(self.skill_id or "").strip():
            raise CanaryError("skill_id must not be empty")
        if self.state not in {item.value for item in RolloutState}:
            raise CanaryError(f"unknown rollout state: {self.state!r}")

    def record_calls(self, *, calls: int, errors: int) -> None:
        if calls < 0 or errors < 0 or errors > calls:
            raise CanaryError("invalid call/error counts")
        self.call_count += int(calls)
        self.error_count += int(errors)
        self.state = RolloutState.RUNNING.value

    def error_rate(self) -> float:
        return (self.error_count / self.call_count) if self.call_count else 0.0


def evaluate_canary(
    rollout: Rollout,
    *,
    threshold: float = DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    min_samples: int = DEFAULT_MIN_CANARY_SAMPLES,
) -> CanaryDecision:
    """Decide whether a canary should roll back (FR-5).

    A rollout with too few samples is **not** rolled back — the error rate is not
    yet meaningful (FR-10).
    """
    rate = rollout.error_rate()
    if rollout.call_count < int(min_samples):
        return CanaryDecision(
            state=rollout.state,
            error_rate=rate,
            should_rollback=False,
            reason=f"样本不足（{rollout.call_count}/{min_samples}），暂不判定",
            sample_sufficient=False,
        )
    if rate > float(threshold):
        return CanaryDecision(
            state=RolloutState.ROLLED_BACK.value,
            error_rate=rate,
            should_rollback=True,
            reason=f"异常率 {rate:.2%} 超过阈值 {threshold:.0%}，回滚到版本 {rollout.stable_version}",
        )
    return CanaryDecision(
        state=rollout.state,
        error_rate=rate,
        should_rollback=False,
        reason="异常率在阈值内",
    )


def apply_rollback(rollout: Rollout, decision: CanaryDecision) -> dict[str, Any]:
    """Apply a rollback decision, returning the audit record (FR-5 / FR-7)."""
    if not decision.should_rollback:
        return {}
    rollout.state = RolloutState.ROLLED_BACK.value
    return {
        "action": "rollback",
        "skillId": rollout.skill_id,
        "fromVersion": rollout.version,
        "toVersion": rollout.stable_version,
        "errorRate": round(decision.error_rate, 4),
        "reason": decision.reason,
    }
