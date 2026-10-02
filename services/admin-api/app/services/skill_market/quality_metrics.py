"""Skill effect-score metric collection + periodic assessment (016 FR-3 / FR-6).

This module closes the 016 write loop that ``adoption_client.apply_quality_assessment``
opens: it owns the *source data* for the effect score. The five counters
(total / successful / adopted / corrected calls, plus a rolling ``sustained_days``)
are stored in a tenant-partitioned ``skill_quality_metrics`` collection as **daily
buckets** keyed by ``(main_id, skill_key, date)``. A periodic ``SkillQualityScanner``
rolls the last ``window_days`` buckets up, computes the weighted effect score, and
persists the result through ``apply_quality_assessment`` into the shared
``skill_adoption`` bit that the market list down-ranks.

The actual *write* side (``record_skill_call``) is intentionally decoupled from any
single service: chat-api records real skill executions into this same collection over
the shared MongoDB (see ``QUALITY_METRICS_COLLECTION``), so 016 only reads and scores.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from app.services.skill_market.adoption_client import (
    apply_quality_assessment,
    restore_quality,
)
from app.services.skill_market.scoring import (
    LOW_QUALITY_SUSTAINED_DAYS,
    LOW_QUALITY_THRESHOLD,
    compute_effect_score,
    is_low_quality,
)

logger = logging.getLogger(__name__)

# The daily-bucket collection chat-api and 016 share (one writer each side agrees on).
QUALITY_METRICS_COLLECTION = "skill_quality_metrics"

# chat-api's projected kernel events — the durable fact stream skill activity is
# read from (011 reads the same collection for tool outcomes).
PROJECTIONS_COLLECTION = "kernel_event_projections"

# Collector high-water mark (single global doc, no tenant key of its own).
COLLECTOR_STATE_COLLECTION = "skill_quality_collector_state"
_COLLECTOR_STATE_ID = "skill_activity"

# Default cadence for the periodic assessment scanner (016 FR-6 window is 7 days,
# but the scanner should run more often than that to keep the bit fresh).
DEFAULT_INTERVAL_SECONDS = 6 * 3600.0

#: Minimum calls inside the window before an effect score may be persisted. Guards
#: against mass-marking healthy skills on partial data (see ``evaluate_skill_quality``).
MIN_EFFECT_SAMPLES = 20


def _today(ts: Optional[datetime] = None) -> date:
    return (ts or datetime.now(timezone.utc)).date()


def _bucket_key(main_id: str, skill_key: str, day: date) -> dict[str, Any]:
    return {"main_id": main_id, "skill_key": skill_key, "date": day.isoformat()}


async def record_skill_call(
    db: Any,
    *,
    main_id: str,
    skill_key: str,
    success: bool = False,
    adopted: int = 0,
    corrected: int = 0,
    day: Optional[date] = None,
) -> None:
    """Record one skill execution into today's bucket (chat-api writes this).

    Counters are additive so partial information is fine: a caller that only knows
    whether the execution succeeded passes ``success``; ``adopted`` / ``corrected``
    default to 0 when the upstream signal is not yet wired (see WORK_LOG — the
    adoption / correction facts are still a platform-level collection gap).
    """
    if db is None:
        return
    key = _bucket_key(main_id, skill_key, day or _today())
    await db[QUALITY_METRICS_COLLECTION].update_one(
        key,
        {
            "$inc": {
                "total_calls": 1,
                "successful_calls": 1 if success else 0,
                "adopted_calls": int(adopted),
                "corrected_calls": int(corrected),
            }
        },
        upsert=True,
    )


async def collect_skill_activity_metrics(
    db: Any,
    *,
    limit: int = 5000,
) -> dict[str, Any]:
    """Roll skill-activity projections into the daily metric buckets (real signal).

    Reads chat-api's ``kernel_event_projections`` (the durable DSH event journal) for
    ``skill.selected`` activity rows — the platform's only real "a skill was loaded
    and executed" fact. Each row increments that tenant/skill/day bucket's
    ``total_calls``. A persisted high-water mark (``stream_seq``) makes the pass
    idempotent across restarts.

    Only ``total_calls`` can be derived here: the activity event has no
    success/adoption/correction verdict. ``evaluate_skill_quality`` therefore refuses
    to score until the richer dimensions exist (see its completeness gate).
    """
    if db is None:
        return {"collected": 0, "last_stream_seq": 0}
    state = await db[COLLECTOR_STATE_COLLECTION].find_one({"_id": _COLLECTOR_STATE_ID})
    after = int((state or {}).get("last_stream_seq") or 0)
    rows = (
        await db[PROJECTIONS_COLLECTION]
        .find(
            {
                "item_kind": "activity",
                "type": "item.completed",
                "payload.category": "skill",
                "stream_seq": {"$gt": after},
            },
            {
                "_id": 0,
                "tenant_id": 1,
                "item_id": 1,
                "stream_seq": 1,
                "payload": 1,
                "created_at": 1,
            },
        )
        .sort("stream_seq", 1)
        .limit(int(limit))
        .to_list(length=int(limit))
    )
    collected = 0
    last = after
    for row in rows:
        tenant_id = str(row.get("tenant_id") or "")
        skill_key = _skill_key_from_activity(row)
        if not tenant_id or not skill_key:
            last = max(last, int(row.get("stream_seq") or 0))
            continue
        day = row.get("created_at")
        day = day.date() if isinstance(day, datetime) else _today()
        await record_skill_call(db, main_id=tenant_id, skill_key=skill_key, day=day)
        collected += 1
        last = max(last, int(row.get("stream_seq") or 0))
    if last > after:
        await db[COLLECTOR_STATE_COLLECTION].update_one(
            {"_id": _COLLECTOR_STATE_ID},
            {"$set": {"last_stream_seq": last}},
            upsert=True,
        )
    return {"collected": collected, "last_stream_seq": last}


def _skill_key_from_activity(row: dict[str, Any]) -> str:
    """Recover the skill key from a projected ``skill.selected`` activity row.

    The projector builds ``item_id = f"{message_id}:selected-skill:{source_id}"``;
    ``source_id`` is the control-plane skill id the market keys on. Falls back to
    the display name when the id is not recoverable.
    """
    item_id = str(row.get("item_id") or "")
    marker = ":selected-skill:"
    if marker in item_id:
        source_id = item_id.split(marker, 1)[1].strip()
        if source_id:
            return source_id
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return str(payload.get("skill_name") or "").strip()


async def _aggregate(
    db: Any,
    *,
    main_id: str,
    skill_key: str,
    window_days: int,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Sum the last ``window_days`` buckets and compute a rolling sustained window."""
    today = as_of or _today()
    cutoff = (today.toordinal() - (window_days - 1))
    start = date.fromordinal(cutoff)
    rows = (
        await db[QUALITY_METRICS_COLLECTION]
        .find(
            {
                "main_id": main_id,
                "skill_key": skill_key,
                "date": {"$gte": start.isoformat(), "$lte": today.isoformat()},
            }
        )
        .to_list(length=window_days + 1)
    )
    totals = {"total_calls": 0, "successful_calls": 0, "adopted_calls": 0, "corrected_calls": 0}
    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        for k in totals:
            totals[k] += int(row.get(k) or 0)
        by_day[row.get("date")] = row

    if totals["total_calls"] == 0:
        return {**totals, "effect_score": 0.0, "sustained_low_days": 0}

    effect = compute_effect_score(
        total_calls=totals["total_calls"],
        successful_calls=totals["successful_calls"],
        adopted_calls=totals["adopted_calls"],
        corrected_calls=totals["corrected_calls"],
    )
    # Rolling sustained window: walk backwards from today counting consecutive
    # low-quality days. A missing day breaks the streak (conservative).
    sustained = 0
    for offset in range(0, window_days):
        cur = date.fromordinal(today.toordinal() - offset)
        bucket = by_day.get(cur.isoformat())
        if bucket is None:
            break
        day_total = int(bucket.get("total_calls") or 0)
        if day_total == 0:
            break
        day_effect = compute_effect_score(
            total_calls=day_total,
            successful_calls=int(bucket.get("successful_calls") or 0),
            adopted_calls=int(bucket.get("adopted_calls") or 0),
            corrected_calls=int(bucket.get("corrected_calls") or 0),
        ).score
        if day_effect < LOW_QUALITY_THRESHOLD:
            sustained += 1
        else:
            break
    return {**totals, "effect_score": effect.score, "sustained_low_days": sustained}


async def evaluate_skill_quality(
    db: Any,
    *,
    main_id: str,
    skill_key: str,
    window_days: int = LOW_QUALITY_SUSTAINED_DAYS,
    min_samples: int = MIN_EFFECT_SAMPLES,
) -> dict[str, Any]:
    """Roll up the recent buckets, score, and persist the result to ``skill_adoption``.

    Returns the assessment outcome (effect score, sustained days, whether the
    aggregated ``marked_low_quality`` bit is now set).

    Completeness gate: the score is only *persisted* when there is enough data to
    trust it — at least ``min_samples`` calls in the window **and** at least one
    adoption/correction signal. Without this, a window that only carries
    ``total_calls`` (the skill-activity collection is still partial) would score
    ``0.2`` (correction-inverse only) and mass-mark every healthy skill as low
    quality. Incomplete windows are skipped, never marked.
    """
    agg = await _aggregate(db, main_id=main_id, skill_key=skill_key, window_days=window_days)
    sufficient = (
        agg["total_calls"] >= int(min_samples)
        and (agg["adopted_calls"] + agg["corrected_calls"]) > 0
    )
    if not sufficient:
        return {
            "skill_key": skill_key,
            "evaluated": False,
            "reason": "insufficient_signal",
            "total_calls": agg["total_calls"],
            "effect_score": round(agg["effect_score"], 4),
            "sustained_low_days": agg["sustained_low_days"],
            "window_days": window_days,
        }
    outcome = await apply_quality_assessment(
        db,
        main_id=main_id,
        skill_key=skill_key,
        total_calls=agg["total_calls"],
        successful_calls=agg["successful_calls"],
        adopted_calls=agg["adopted_calls"],
        corrected_calls=agg["corrected_calls"],
        sustained_days=agg["sustained_low_days"],
    )
    outcome["evaluated"] = True
    outcome["effect_score"] = round(agg["effect_score"], 4)
    outcome["sustained_low_days"] = agg["sustained_low_days"]
    outcome["window_days"] = window_days
    return outcome


async def evaluate_all(
    db: Any,
    *,
    window_days: int = LOW_QUALITY_SUSTAINED_DAYS,
) -> int:
    """Score every (main_id, skill_key) that has any metric bucket. Returns count."""
    if db is None:
        return 0
    keys = (
        await db[QUALITY_METRICS_COLLECTION]
        .aggregate(
            [
                {"$group": {"_id": {"main_id": "$main_id", "skill_key": "$skill_key"}}},
            ]
        )
        .to_list(length=20000)
    )
    scored = 0
    for row in keys:
        _id = row.get("_id") or {}
        main_id = str(_id.get("main_id") or "")
        skill_key = str(_id.get("skill_key") or "")
        if not main_id or not skill_key:
            continue
        await evaluate_skill_quality(db, main_id=main_id, skill_key=skill_key, window_days=window_days)
        scored += 1
    return scored


class SkillQualityScanner:
    """Periodic trigger for ``evaluate_all`` (started from the app lifespan)."""

    def __init__(
        self,
        *,
        db: Any = None,
        interval_seconds: Optional[float] = None,
        window_days: int = LOW_QUALITY_SUSTAINED_DAYS,
    ) -> None:
        self._db = db
        self._interval_seconds = interval_seconds
        self._window_days = window_days
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        if self._interval_seconds is not None:
            return float(self._interval_seconds)
        return DEFAULT_INTERVAL_SECONDS

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="skill-quality-scanner")

    async def stop(self) -> None:
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
                # Order matters: first fold new skill-activity facts into the daily
                # buckets, then score them.
                await collect_skill_activity_metrics(db)
                await evaluate_all(db, window_days=self._window_days)
            except Exception:  # pragma: no cover - defensive
                logger.exception("skill quality scan failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass
