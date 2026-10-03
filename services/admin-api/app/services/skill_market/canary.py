"""Canary rollout + automatic rollback (016 FR-4 / FR-5 / clarify OQ-2 / OQ-3).

* first delivery rolls out **by tenant** (clarify OQ-2);
* automatic rollback triggers when the canary error rate exceeds **20%**
  (configurable, clarify OQ-3);
* a **minimum sample size** guards against small-sample noise (FR-10).

Rollback target is the Skill's **previous published stable version** (FR-13).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Auto-rollback scheduler (016 FR-5 residual: 自动回滚定时调度)
# ---------------------------------------------------------------------------

ROLLBACK_SCAN_COLLECTION = "skill_rollouts"


def _row_to_rollout(row: dict[str, Any]) -> Rollout:
    return Rollout(
        skill_id=str(row.get("skill_id") or ""),
        version=int(row.get("version") or 0),
        stable_version=int(row.get("stable_version") or 0),
        target_tenants=list(row.get("target_tenants") or []),
        state=str(row.get("state") or "pending"),
        error_count=int(row.get("error_count") or 0),
        call_count=int(row.get("call_count") or 0),
    )


def _rollout_to_row(rollout: Rollout) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "skill_id": rollout.skill_id,
        "version": rollout.version,
        "stable_version": rollout.stable_version,
        "target_tenants": rollout.target_tenants,
        "state": rollout.state,
        "error_count": rollout.error_count,
        "call_count": rollout.call_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def scan_and_auto_rollback(
    db,
    *,
    threshold: float = DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    min_samples: int = DEFAULT_MIN_CANARY_SAMPLES,
) -> list[dict[str, Any]]:
    """Scan all active canary rollouts and apply automatic rollback where
    the error-rate threshold is breached (FR-5 scheduled residual).

    Reads every rollout row whose state is *pending* or *running*, evaluates
    it with the current counts, and — when a rollback is warranted — applies
    the state change and persists it. Returns the list of applied rollback
    records (empty when nothing tripped the threshold).
    """
    collection = db[ROLLBACK_SCAN_COLLECTION]
    rows = await collection.find(
        {"state": {"$in": [RolloutState.PENDING.value, RolloutState.RUNNING.value]}}
    ).to_list(length=500)

    applied: list[dict[str, Any]] = []
    for row in rows:
        rollout = _row_to_rollout(row)
        decision = evaluate_canary(rollout, threshold=threshold, min_samples=min_samples)
        result = apply_rollback(rollout, decision)
        if result:
            await collection.replace_one(
                {"skill_id": rollout.skill_id}, _rollout_to_row(rollout)
            )
            applied.append(result)
            logger.info(
                "canary auto-rollback applied",
                extra={"event": "canary.auto_rollback", **result},
            )
    return applied


class CanaryRollbackScanner:
    """Periodic trigger for :func:`scan_and_auto_rollback` (lifespan-managed)."""

    def __init__(
        self,
        *,
        db: Any = None,
        interval_seconds: Optional[float] = None,
        threshold: float = DEFAULT_CANARY_ROLLBACK_THRESHOLD,
        min_samples: int = DEFAULT_MIN_CANARY_SAMPLES,
    ) -> None:
        self._db = db
        self._interval_seconds = interval_seconds
        self._threshold = threshold
        self._min_samples = min_samples
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        if self._interval_seconds is not None:
            return float(self._interval_seconds)
        return 300.0  # 5 minutes

    async def start(self) -> None:
        import contextlib

        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="canary-rollback-scanner")

    async def stop(self) -> None:
        import contextlib

        self._stopping.set()
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        from app.core.db import get_db

        while not self._stopping.is_set():
            try:
                db = self._db if self._db is not None else get_db()
                await scan_and_auto_rollback(
                    db, threshold=self._threshold, min_samples=self._min_samples
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("canary auto-rollback scan failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass
