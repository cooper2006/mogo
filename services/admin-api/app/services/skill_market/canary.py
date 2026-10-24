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

# ---------------------------------------------------------------------------
# 033-canary-rollout: 比例灰度 + 影子发布 增量（016 语义原样保留）
# ---------------------------------------------------------------------------

#: 阶梯默认档位：1% → 10% → 50% → 100%（决策表第 4 条）。
DEFAULT_TRAFFIC_LADDER: tuple[float, ...] = (0.01, 0.10, 0.50, 1.00)

#: 影子分流基数（百分比分母），分流为 O(1) 确定性纯函数。
TRAFFIC_BUCKETS = 10000

#: 影子模式默认 ratio 参考值，复用 011 ``DEFAULT_SHADOW_RATIO=0.1``（决策表第 6 条）。
DEFAULT_SHADOW_RATIO = 0.10

#: 影子观察记录集合（只写 + 基础聚合查询，YAGNI）。
SHADOW_RUNS_COLLECTION = "skill_shadow_runs"


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


def _utcnow() -> str:
    """UTC ISO-8601 timestamp (string) — stable across Mongo / PanWeiDB backends."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def default_ladder() -> list["LadderStep"]:
    """Build the default traffic ladder (1% → 10% → 50% → 100%)."""
    return [LadderStep(ratio=ratio) for ratio in DEFAULT_TRAFFIC_LADDER]


@dataclass
class LadderStep:
    """A single rung in the traffic ladder (033 FR-001)."""

    ratio: float
    min_samples: Optional[int] = None      # per-rung override; None → global min_samples
    entered_at: str = ""
    promoted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratio": round(float(self.ratio), 4),
            "min_samples": self.min_samples,
            "entered_at": self.entered_at,
            "promoted_at": self.promoted_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "LadderStep":
        data = dict(data or {})
        return cls(
            ratio=float(data.get("ratio") or 0.0),
            min_samples=int(data["min_samples"]) if data.get("min_samples") not in (None, "", 0) else None,
            entered_at=str(data.get("entered_at") or ""),
            promoted_at=str(data.get("promoted_at") or ""),
        )


@dataclass
class LadderDecision:
    """Outcome of evaluating one step of the ladder (033 FR-004)."""

    advanced: bool
    promoted: bool
    current_step: int
    traffic_ratio: float
    reason: str
    min_samples_required: int


@dataclass
class ShadowOutcome:
    """Outcome of a shadow dual-run (033 FR-006/FR-007/FR-008)."""

    skipped: bool = False
    recorded: bool = False
    ok: bool = False
    duration_ms: int = 0
    error: str = ""


@dataclass
class Rollout:
    """A canary rollout of one Skill version to a set of tenants.

    033-canary-rollout 扩展：在 016 按租户灰度的语义之上增加
    ``traffic_ratio`` / ``ladder`` / ``current_step`` / ``ladder_history`` /
    ``shadow_enabled`` 五个维度；存量行（无新字段）读取时回退到
    ``ratio=1.0``、``shadow=False``（决策表第 10 条），016 既有按租户灰度行为不回退。
    """

    skill_id: str
    version: int
    stable_version: int = 0                 # the version to roll back to
    target_tenants: list[str] = field(default_factory=list)
    state: str = RolloutState.PENDING.value
    error_count: int = 0
    call_count: int = 0
    # 033 新增维度
    traffic_ratio: float = 1.0              # 当前生效分流比例（0 < ratio ≤ 1）
    ladder: list[LadderStep] = field(default_factory=default_ladder)
    current_step: int = 0
    ladder_history: list[dict[str, Any]] = field(default_factory=list)
    shadow_enabled: bool = False

    def __post_init__(self) -> None:
        if not str(self.skill_id or "").strip():
            raise CanaryError("skill_id must not be empty")
        if self.state not in {item.value for item in RolloutState}:
            raise CanaryError(f"unknown rollout state: {self.state!r}")
        # 033 校验：traffic_ratio 必须在 [0, 1] 内（0 表示回滚后流量归零；
        # 创建/更新时的「0 < ratio ≤ 1」严格校验在路由层，见 skill_canary.py）。
        if not 0.0 <= float(self.traffic_ratio) <= 1.0:
            raise CanaryError(
                f"traffic_ratio must be in [0, 1], got {self.traffic_ratio!r}"
            )
        if not self.ladder:
            self.ladder = default_ladder()
        # 归一化：把 plain dict 阶梯项转为 LadderStep（兼容直接构造）。
        self.ladder = [
            item if isinstance(item, LadderStep) else LadderStep.from_dict(item)
            for item in self.ladder
        ]
        # 保证 current_step 落在合法区间。
        self.current_step = max(0, min(int(self.current_step), len(self.ladder) - 1))

    @property
    def current_ratio(self) -> float:
        """当前生效分流比例（= ``traffic_ratio``，权威值，:func:`resolve_assignment` 使用）。

        对新建 rollout 而言它与 ``ladder[current_step].ratio`` 一致；对 016 存量行
        （无 ladder 字段，ratio=1.0）它才是真实流量，故以 traffic_ratio 为准，
        避免把已 100% 的灰度误判为 1% 档而反向缩量。
        """
        return float(self.traffic_ratio)

    @property
    def rung_ratio(self) -> float:
        """当前阶梯档位的标称比例（仅阶梯展示用）。"""
        return float(self.ladder[self.current_step].ratio)

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
    """Apply a rollback decision, returning the audit record (FR-5 / FR-7).

    033 增量：回滚后 ``traffic_ratio`` 归零（决策表/edge case「回滚目标」），
    ``state`` 置 ``rolled_back``，流量切回 ``stable_version``。
    """
    if not decision.should_rollback:
        return {}
    rollout.state = RolloutState.ROLLED_BACK.value
    rollout.traffic_ratio = 0.0
    return {
        "action": "rollback",
        "skillId": rollout.skill_id,
        "fromVersion": rollout.version,
        "toVersion": rollout.stable_version,
        "errorRate": round(decision.error_rate, 4),
        "reason": decision.reason,
    }


# ---------------------------------------------------------------------------
# 033-canary-rollout: 分流纯函数 / 阶梯推进器 / 影子记录
# ---------------------------------------------------------------------------

def _traffic_bucket(tenant_id: str, user_id: str) -> int:
    """Deterministic hash of ``(tenant_id, user_id)`` → bucket in [0, TRAFFIC_BUCKETS).

    Uses SHA-256 (unlike Python's salted ``hash()``) so the assignment is stable
    across processes/replicas (FR-003 user stickiness). Pure, O(1), no IO.
    """
    import hashlib

    digest = hashlib.sha256(f"{tenant_id}:{user_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % TRAFFIC_BUCKETS


def resolve_assignment(rollout: Rollout, *, tenant_id: str, user_id: str) -> bool:
    """Decide whether *user* should be routed to the canary (candidate) version.

    * ``target_tenants`` gates a tenant subset; empty list means "all tenants"
      (FR-002);
    * inside that subset ``traffic_ratio`` fans the traffic out by user, using a
      deterministic hash so the same user always lands in the same group during
      the whole rollout (FR-003, decision table #3).

    The function is a pure, side-effect-free decision — no IO, no state.
    """
    ratio = float(rollout.traffic_ratio)
    if not 0.0 < ratio <= 1.0:
        raise CanaryError(
            f"traffic_ratio must be in (0, 1] to route traffic, got {ratio!r}"
        )
    if rollout.target_tenants and str(tenant_id) not in {str(t) for t in rollout.target_tenants}:
        return False
    bucket = _traffic_bucket(str(tenant_id), str(user_id))
    return bucket < max(1, round(ratio * TRAFFIC_BUCKETS))


def should_shadow(rollout: Rollout, *, tenant_id: str, user_id: str) -> bool:
    """Whether this user's request should trigger a shadow dual-run (FR-006).

    A user who *hits* the canary ratio already runs the candidate version for real,
    so no shadowing is needed (decision table #5); users who miss it get the
    stable version AND a shadow run when ``shadow_enabled`` is on.
    """
    if not rollout.shadow_enabled:
        return False
    if resolve_assignment(rollout, tenant_id=tenant_id, user_id=user_id):
        return False
    return True


def advance_ladder(
    rollout: Rollout,
    *,
    min_samples: int = DEFAULT_MIN_CANARY_SAMPLES,
    threshold: float = DEFAULT_CANARY_ROLLBACK_THRESHOLD,
) -> LadderDecision:
    """Evaluate and (when eligible) advance the traffic ladder (FR-004/FR-005/FR-011).

    Rules (decision table #4, edge case「阶梯推进中样本不足」):
    * a terminal state (``promoted`` / ``rolled_back``) never advances;
    * below ``min_samples`` for the current rung → stay (small-sample protection,
      same spirit as 016 FR-10);
    * error rate above ``threshold`` → stay; the rollback scanner owns that case
      (033 does not change 016 rollback semantics);
    * otherwise advance to the next rung, persist the step, and set
      ``traffic_ratio`` to the new rung's ratio;
    * on the final rung (ratio == 1.0) with a sufficient, healthy sample the
      rollout is marked ``PROMOTED`` (FR-011) and the ladder is complete.
    """
    if rollout.state in (RolloutState.PROMOTED.value, RolloutState.ROLLED_BACK.value):
        return LadderDecision(
            advanced=False,
            promoted=rollout.state == RolloutState.PROMOTED.value,
            current_step=rollout.current_step,
            traffic_ratio=round(float(rollout.traffic_ratio), 4),
            reason=f"状态 {rollout.state} 不参与阶梯推进",
            min_samples_required=int(min_samples),
        )

    step = rollout.ladder[rollout.current_step]
    rung_min = int(step.min_samples or min_samples)
    rate = rollout.error_rate()

    if rollout.call_count < rung_min:
        return LadderDecision(
            advanced=False,
            promoted=False,
            current_step=rollout.current_step,
            traffic_ratio=round(float(rollout.traffic_ratio), 4),
            reason=f"样本不足（{rollout.call_count}/{rung_min}），停在当前档 {step.ratio:.0%}",
            min_samples_required=rung_min,
        )
    if rate > float(threshold):
        return LadderDecision(
            advanced=False,
            promoted=False,
            current_step=rollout.current_step,
            traffic_ratio=round(float(rollout.traffic_ratio), 4),
            reason=f"异常率 {rate:.2%} 超过阈值 {threshold:.0%}，暂停推进（回滚由扫描器判定）",
            min_samples_required=rung_min,
        )

    # 当前档达标：若已是末档（100%）→ promoted；否则推进到下一档。
    if rollout.current_ratio >= 1.0 or rollout.current_step >= len(rollout.ladder) - 1:
        rollout.state = RolloutState.PROMOTED.value
        rollout.ladder_history.append(
            {
                "step": rollout.current_step,
                "ratio": round(float(step.ratio), 4),
                "entered_at": step.entered_at,
                "promoted_at": _utcnow(),
                "error_rate": round(rate, 4),
                "call_count": rollout.call_count,
            }
        )
        return LadderDecision(
            advanced=True,
            promoted=True,
            current_step=rollout.current_step,
            traffic_ratio=round(float(rollout.traffic_ratio), 4),
            reason="已达 100% 且样本/异常率稳定，灰度结束（PROMOTED）",
            min_samples_required=rung_min,
        )

    next_index = rollout.current_step + 1
    next_step = rollout.ladder[next_index]
    now = _utcnow()
    rollout.ladder_history.append(
        {
            "step": rollout.current_step,
            "ratio": round(float(step.ratio), 4),
            "entered_at": step.entered_at,
            "promoted_at": now,
            "error_rate": round(rate, 4),
            "call_count": rollout.call_count,
        }
    )
    rollout.current_step = next_index
    rollout.traffic_ratio = next_step.ratio
    if not next_step.entered_at:
        next_step.entered_at = now
    rollout.state = RolloutState.RUNNING.value
    return LadderDecision(
        advanced=True,
        promoted=False,
        current_step=next_index,
        traffic_ratio=round(float(next_step.ratio), 4),
        reason=f"档位 {step.ratio:.0%} → {next_step.ratio:.0%}（样本 {rollout.call_count}，异常率 {rate:.2%}）",
        min_samples_required=rung_min,
    )


async def record_shadow_run(
    db,
    *,
    skill_id: str,
    version: int,
    tenant_id: str,
    user_id: str,
    duration_ms: int,
    ok: bool,
    error: str = "",
) -> dict[str, Any]:
    """Persist one shadow observation into ``skill_shadow_runs`` (FR-008).

    Write-only from the user path; the record is never returned to the user and
    never feeds ``call_count`` / ``error_count``, so it cannot trigger a rollback.
    """
    doc: dict[str, Any] = {
        "skill_id": str(skill_id),
        "version": int(version),
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "duration_ms": int(duration_ms),
        "ok": bool(ok),
        "error": str(error or ""),
        "created_at": _utcnow(),
    }
    await db[SHADOW_RUNS_COLLECTION].insert_one(doc)
    return doc


async def fetch_shadow_stats(
    db,
    *,
    skill_id: str,
    version: Optional[int] = None,
    sample_limit: int = 500,
) -> dict[str, Any]:
    """Basic aggregate statistics over shadow runs (FR-012, YAGNI — no deep compare)."""
    coll = db[SHADOW_RUNS_COLLECTION]
    query: dict[str, Any] = {"skill_id": str(skill_id)}
    if version is not None:
        query["version"] = int(version)

    total = int(await coll.count_documents(query) or 0)
    ok_count = int(await coll.count_documents({**query, "ok": True}) or 0)
    durations: list[float] = []
    if total:
        recent = await coll.find(query).to_list(length=min(sample_limit, total))
        for row in recent:
            value = row.get("duration_ms")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                durations.append(float(value))
    return {
        "skill_id": str(skill_id),
        "version": version,
        "total": total,
        "ok": ok_count,
        "success_rate": round((ok_count / total), 4) if total else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0,
    }


# ---------------------------------------------------------------------------
# Auto-rollback scheduler (016 FR-5 residual: 自动回滚定时调度)
# ---------------------------------------------------------------------------

ROLLBACK_SCAN_COLLECTION = "skill_rollouts"


def _normalize_ladder(raw: Any) -> list[LadderStep]:
    """Normalise a stored ladder value into :class:`LadderStep` list.

    Legacy rows have no ``ladder`` field at all → default ladder (1%→10%→50%→100%).
    """
    if not raw:
        return default_ladder()
    return [LadderStep.from_dict(item) for item in raw if isinstance(item, (dict, LadderStep))]


def _row_to_rollout(row: dict[str, Any]) -> Rollout:
    # 033 决策表第 10 条：存量行缺新字段 → ratio=1.0 / shadow=False（016 不回退）。
    return Rollout(
        skill_id=str(row.get("skill_id") or ""),
        version=int(row.get("version") or 0),
        stable_version=int(row.get("stable_version") or 0),
        target_tenants=list(row.get("target_tenants") or []),
        state=str(row.get("state") or "pending"),
        error_count=int(row.get("error_count") or 0),
        call_count=int(row.get("call_count") or 0),
        traffic_ratio=float(row.get("traffic_ratio") or 1.0),
        ladder=_normalize_ladder(row.get("ladder")),
        current_step=int(row.get("current_step") or 0),
        ladder_history=list(row.get("ladder_history") or []),
        shadow_enabled=bool(row.get("shadow_enabled") or False),
    )


def _rollout_to_row(rollout: Rollout) -> dict[str, Any]:
    return {
        "skill_id": rollout.skill_id,
        "version": rollout.version,
        "stable_version": rollout.stable_version,
        "target_tenants": rollout.target_tenants,
        "state": rollout.state,
        "error_count": rollout.error_count,
        "call_count": rollout.call_count,
        "traffic_ratio": round(float(rollout.traffic_ratio), 4),
        "ladder": [step.to_dict() for step in rollout.ladder],
        "current_step": rollout.current_step,
        "ladder_history": rollout.ladder_history,
        "shadow_enabled": bool(rollout.shadow_enabled),
        "updated_at": _utcnow(),
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


async def scan_and_advance_ladder(
    db,
    *,
    min_samples: int = DEFAULT_MIN_CANARY_SAMPLES,
    threshold: float = DEFAULT_CANARY_ROLLBACK_THRESHOLD,
) -> list[dict[str, Any]]:
    """033: periodically evaluate and (when eligible) advance the traffic ladder.

    Runs on the same 5-minute cadence as :func:`scan_and_auto_rollback`
    (decision table #4, FR-004/FR-005): a rung whose sample is sufficient and
    whose error rate is healthy moves to the next rung; the final rung promotes
    the rollout. Rollback priority is preserved — a rollout already rolled back
    by the companion scan is skipped here (terminal state).
    """
    collection = db[ROLLBACK_SCAN_COLLECTION]
    rows = await collection.find(
        {"state": {"$in": [RolloutState.PENDING.value, RolloutState.RUNNING.value]}}
    ).to_list(length=500)

    advanced: list[dict[str, Any]] = []
    for row in rows:
        rollout = _row_to_rollout(row)
        decision = advance_ladder(
            rollout, min_samples=min_samples, threshold=threshold
        )
        if not decision.advanced:
            continue
        await collection.replace_one({"skill_id": rollout.skill_id}, _rollout_to_row(rollout))
        record: dict[str, Any] = {
            "action": "ladder_advance" if not decision.promoted else "promote",
            "skillId": rollout.skill_id,
            "version": rollout.version,
            "step": decision.current_step,
            "trafficRatio": decision.traffic_ratio,
            "promoted": decision.promoted,
            "reason": decision.reason,
        }
        advanced.append(record)
        logger.info("canary ladder advanced", extra={"event": "canary.ladder_advance", **record})
    return advanced


class CanaryRollbackScanner:
    """Periodic trigger for :func:`scan_and_auto_rollback` (lifespan-managed).

    033 增量：同一个 5 分钟循环里，回滚判定之后额外执行
    :func:`scan_and_advance_ladder`，实现决策表第 4 条的「自动评估并推进」。
    """

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
                await scan_and_advance_ladder(
                    db, threshold=self._threshold, min_samples=self._min_samples
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("canary auto-rollback scan failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass
