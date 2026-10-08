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
from datetime import date, datetime, timedelta, timezone
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

# chat-api's accepted authoritative deliveries (OQ-6 adoption source).
DELIVERIES_COLLECTION = "enterprise_authoritative_deliveries"

# chat-api's tool execution receipts (OQ-6 success source).
RECEIPTS_COLLECTION = "enterprise_action_receipts"

# chat-api's product-edit events written by POST /documents/save-blueprint (OQ-6
# correction source). Newly instrumented — chat-api owns the writer.
EDIT_EVENTS_COLLECTION = "skill_product_edit_events"

# Success is attributed at kernel-session level (± this window around the skill
# activity), because receipts carry no message_id (see EnterpriseActionReceipt).
DEFAULT_SUCCESS_WINDOW_SECONDS = 30 * 60

# Collector high-water marks (single global docs, no tenant key of their own).
COLLECTOR_STATE_COLLECTION = "skill_quality_collector_state"
_COLLECTOR_STATE_ID = "skill_activity"
_EDIT_STATE_ID = "product_edit"

# Default cadence for the periodic assessment scanner (016 FR-6 window is 7 days,
# but the scanner should run more often than that to keep the bit fresh).
DEFAULT_INTERVAL_SECONDS = 6 * 3600.0

#: Minimum calls inside the window before an effect score may be persisted. Guards
#: against mass-marking healthy skills on partial data (see ``evaluate_skill_quality``).
MIN_EFFECT_SAMPLES = 20


def _today(ts: Optional[datetime] = None) -> date:
    return (ts or datetime.now(timezone.utc)).date()


def _bucket_key(tenant_id: str, skill_key: str, day: date) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "skill_key": skill_key, "date": day.isoformat()}


async def record_skill_call(
    db: Any,
    *,
    tenant_id: str,
    skill_key: str,
    success: bool = False,
    adopted: int = 0,
    corrected: int = 0,
    day: Optional[date] = None,
    track_success: bool = False,
) -> None:
    """Record one skill execution into today's bucket.

    ``track_success=True`` marks the bucket as carrying a *real* success verdict
    (set by the collector, which attributes success from tool receipts). Buckets
    without the flag are legacy total-only data and are refused by the scoring
    completeness gate, so partial data can never mass-mark healthy skills.
    """
    if db is None:
        return
    key = _bucket_key(tenant_id, skill_key, day or _today())
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
    if track_success:
        await db[QUALITY_METRICS_COLLECTION].update_one(
            key, {"$set": {"success_tracked": True}}, upsert=True
        )


async def collect_skill_activity_metrics(
    db: Any,
    *,
    limit: int = 5000,
    success_window_seconds: int = DEFAULT_SUCCESS_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Roll skill-activity projections into the daily metric buckets (real signal).

    Reads chat-api's ``kernel_event_projections`` (the durable DSH event journal) for
    ``skill.selected`` activity rows — the platform's real "a skill was loaded and
    executed" fact. Each row increments that tenant/skill/day bucket, and two
    richer dimensions are attributed from other durable chat-api collections over
    the same MongoDB (all data already exists; no new runtime instrumentation):

    * ``adopted``  — OQ-6: this row's ``message_id`` has an accepted authoritative
      delivery (``enterprise_authoritative_deliveries``, ``accepted=True``).
    * ``successful`` — OQ-6: no ``failed``/``timed_out`` tool receipt
      (``enterprise_action_receipts``) in the same ``kernel_session_id`` within
      ``success_window_seconds`` of the skill activity.

    A persisted high-water mark (``stream_seq``) makes the pass idempotent.
    ``corrected`` is supplied by the edit-event path (see ``collect_edit_events``).
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
                "user_id": 1,
                "message_id": 1,
                "kernel_session_id": 1,
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
        adopted = await _was_adopted(
            db,
            tenant_id=tenant_id,
            message_id=str(row.get("message_id") or ""),
        )
        success = await _was_successful(
            db,
            kernel_session_id=str(row.get("kernel_session_id") or ""),
            at=row.get("created_at"),
            window_seconds=success_window_seconds,
        )
        await record_skill_call(
            db,
            tenant_id=tenant_id,
            skill_key=skill_key,
            success=success,
            adopted=1 if adopted else 0,
            day=day,
            track_success=True,
        )
        collected += 1
        last = max(last, int(row.get("stream_seq") or 0))
    if last > after:
        await db[COLLECTOR_STATE_COLLECTION].update_one(
            {"_id": _COLLECTOR_STATE_ID},
            {"$set": {"last_stream_seq": last}},
            upsert=True,
        )
    return {"collected": collected, "last_stream_seq": last}


async def collect_edit_events(db: Any, *, limit: int = 5000) -> dict[str, Any]:
    """Roll product-edit events into ``corrected_calls`` (OQ-6 correction source).

    chat-api records one event per ``POST /documents/save-blueprint`` (an edited
    product artifact). Each event increments that tenant/skill/day bucket's
    ``corrected_calls``. ``_id`` (ObjectId, monotonic) is the high-water mark, so
    the pass is idempotent across restarts.
    """
    if db is None:
        return {"collected": 0}
    state = await db[COLLECTOR_STATE_COLLECTION].find_one({"_id": _EDIT_STATE_ID})
    after_id = (state or {}).get("last_id")
    flt: dict[str, Any] = {}
    if after_id is not None:
        flt["_id"] = {"$gt": after_id}
    rows = (
        await db[EDIT_EVENTS_COLLECTION]
        .find(flt, {"tenant_id": 1, "message_id": 1, "skill_key": 1, "created_at": 1})
        .sort("_id", 1)
        .limit(int(limit))
        .to_list(length=int(limit))
    )
    collected = 0
    last_id = after_id
    for row in rows:
        tenant_id = str(row.get("tenant_id") or "")
        last_id = row.get("_id", last_id)
        if not tenant_id:
            continue
        skill_key = str(row.get("skill_key") or "") or await _skill_key_for_message(
            db, message_id=str(row.get("message_id") or "")
        )
        if not skill_key:
            continue
        created = row.get("created_at")
        day = created.date() if isinstance(created, datetime) else _today()
        await record_skill_call(
            db, tenant_id=tenant_id, skill_key=skill_key, corrected=1, day=day
        )
        collected += 1
    if last_id is not None and last_id != after_id:
        await db[COLLECTOR_STATE_COLLECTION].update_one(
            {"_id": _EDIT_STATE_ID},
            {"$set": {"last_id": last_id}},
            upsert=True,
        )
    return {"collected": collected}


async def _skill_key_for_message(db: Any, *, message_id: str) -> str:
    """Attribute an edit event to the skill used on its chat turn (OQ-6).

    A turn may load several skills (DSH auto-loads skills as ``automatic``, while the
    user's explicit pick is a single ``manual`` selection). A product edit is credited
    to the skill that actually drove the turn:

    1. the ``manual`` skill when the turn has one — that is the user's stated intent;
    2. otherwise the first ``automatic`` skill (earliest ``stream_seq``).

    Attribution is deliberately a *single* skill per edit: one edit yields one
    artifact, so crediting every skill of the turn would inflate the correction rate.
    Returns "" when the turn used no skill (nothing to charge).
    """
    if not message_id:
        return ""
    rows = (
        await db[PROJECTIONS_COLLECTION]
        .find(
            {"message_id": message_id, "item_kind": "activity", "payload.category": "skill"},
            {"item_id": 1, "payload": 1, "stream_seq": 1},
        )
        .sort("stream_seq", 1)
        .limit(50)
        .to_list(length=50)
    )
    if not rows:
        return ""
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if str(payload.get("selection_mode") or "") == "manual":
            key = _skill_key_from_activity(row)
            if key:
                return key
    return _skill_key_from_activity(rows[0])


async def _was_adopted(db: Any, *, tenant_id: str, message_id: str) -> bool:
    """OQ-6 adoption: an accepted authoritative delivery exists for this message."""
    if not message_id:
        return False
    row = await db[DELIVERIES_COLLECTION].find_one(
        {"tenant_id": tenant_id, "message_id": message_id, "accepted": True},
        {"_id": 1},
    )
    return row is not None


async def _was_successful(
    db: Any,
    *,
    kernel_session_id: str,
    at: Any,
    window_seconds: int,
) -> bool:
    """OQ-6 success: no failed/timed-out tool receipt near this skill activity.

    Receipts carry no ``message_id`` (see ``EnterpriseActionReceipt``), so success is
    attributed at the kernel-session level over a time window around the activity.
    """
    if not kernel_session_id:
        return True
    flt: dict[str, Any] = {
        "kernel_session_id": kernel_session_id,
        "status": {"$in": ["failed", "timed_out"]},
    }
    if isinstance(at, datetime):
        flt["created_at"] = {
            "$gte": at - timedelta(seconds=int(window_seconds)),
            "$lte": at + timedelta(seconds=int(window_seconds)),
        }
    row = await db[RECEIPTS_COLLECTION].find_one(flt, {"_id": 1})
    return row is None


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
    tenant_id: str,
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
                "tenant_id": tenant_id,
                "skill_key": skill_key,
                "date": {"$gte": start.isoformat(), "$lte": today.isoformat()},
            }
        )
        .to_list(length=window_days + 1)
    )
    totals = {"total_calls": 0, "successful_calls": 0, "adopted_calls": 0, "corrected_calls": 0}
    by_day: dict[str, dict[str, int]] = {}
    success_tracked = False
    for row in rows:
        for k in totals:
            totals[k] += int(row.get(k) or 0)
        success_tracked = success_tracked or bool(row.get("success_tracked"))
        by_day[row.get("date")] = row

    if totals["total_calls"] == 0:
        return {
            **totals,
            "effect_score": 0.0,
            "sustained_low_days": 0,
            "success_tracked": success_tracked,
        }

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
    return {
        **totals,
        "effect_score": effect.score,
        "sustained_low_days": sustained,
        "success_tracked": success_tracked,
    }


async def evaluate_skill_quality(
    db: Any,
    *,
    tenant_id: str,
    skill_key: str,
    window_days: int = LOW_QUALITY_SUSTAINED_DAYS,
    min_samples: int = MIN_EFFECT_SAMPLES,
) -> dict[str, Any]:
    """Roll up the recent buckets, score, and persist the result to ``skill_adoption``.

    Returns the assessment outcome (effect score, sustained days, whether the
    aggregated ``marked_low_quality`` bit is now set).

    Completeness gate: the score is only *persisted* when there is enough trustworthy
    data — at least ``min_samples`` calls in the window **and** the window carries a
    real success verdict (``success_tracked``, set by the collector when it
    attributes success from tool receipts). Legacy total-only buckets would score
    ``0.2`` (correction-inverse only) and mass-mark healthy skills as low quality;
    they are skipped, never marked. Once the success dimension is present, adoption
    and correction legitimately default to 0 (a real "not adopted / not corrected").
    """
    agg = await _aggregate(db, tenant_id=tenant_id, skill_key=skill_key, window_days=window_days)
    sufficient = agg["total_calls"] >= int(min_samples) and bool(agg["success_tracked"])
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
        tenant_id=tenant_id,
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
                {"$group": {"_id": {"tenant_id": "$main_id", "skill_key": "$skill_key"}}},
            ]
        )
        .to_list(length=20000)
    )
    scored = 0
    for row in keys:
        _id = row.get("_id") or {}
        tenant_id = str(_id.get("tenant_id") or "")
        skill_key = str(_id.get("skill_key") or "")
        if not tenant_id or not skill_key:
            continue
        await evaluate_skill_quality(db, tenant_id=tenant_id, skill_key=skill_key, window_days=window_days)
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
                # Order matters: first fold new facts into the daily buckets, then
                # score them.
                await collect_skill_activity_metrics(db)
                await collect_edit_events(db)
                await evaluate_all(db, window_days=self._window_days)
            except Exception:  # pragma: no cover - defensive
                logger.exception("skill quality scan failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass
