"""chat-api side of the 016 skill-quality metric buckets — DO NOT WIRE (superseded).

⚠️ Superseded: 016's collection pass now reads the durable DSH event journal
directly (admin-api ``skill_market.quality_metrics.collect_skill_activity_metrics``
rolls ``kernel_event_projections`` skill-activity rows into the same daily buckets,
with an idempotent ``stream_seq`` watermark). Writing from here as well would
**double-count** ``total_calls`` for the same execution.

This module is kept (nothing is deleted per repo policy) as the ready-made entry
point for the *rich* dimensions the event journal cannot supply — ``success`` /
``adopted`` / ``corrected``. Those facts still have no production source (the same
platform-level gap as 011's ``AdoptionStore.record_adoption``). If a future round
adds a real skill-outcome signal, route it through here **only after** removing the
overlapping field from the collector, so the two writers stay disjoint.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

# Must match admin-api ``skill_market.quality_metrics.QUALITY_METRICS_COLLECTION``.
QUALITY_METRICS_COLLECTION = "skill_quality_metrics"
# Must match admin-api ``skill_market.quality_metrics.EDIT_EVENTS_COLLECTION``.
EDIT_EVENTS_COLLECTION = "skill_product_edit_events"


def _today(ts: Optional[datetime] = None) -> date:
    return (ts or datetime.now(timezone.utc)).date()


async def record_product_edit(
    db: Any,
    *,
    tenant_id: str,
    user_id: str,
    object_path: str,
    message_id: str = "",
) -> None:
    """OQ-6 correction signal: a user edited and saved a generated product artifact.

    Written by ``POST /documents/save-blueprint``. 016's collector
    (``quality_metrics.collect_edit_events``) rolls these into ``corrected_calls``,
    attributing the edit to the skill used on ``message_id``. An empty
    ``message_id`` (the artifact could not be traced back to a chat turn) is still
    recorded but cannot be attributed, so it is skipped rather than mis-counted.
    """
    if db is None:
        return
    await db[EDIT_EVENTS_COLLECTION].insert_one(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "object_path": str(object_path or ""),
            "message_id": str(message_id or ""),
            "created_at": datetime.now(timezone.utc),
        }
    )


def report_skill_call(
    db: Any,
    *,
    tenant_id: str,
    skill_key: str,
    success: bool = False,
    adopted: int = 0,
    corrected: int = 0,
    day: Optional[date] = None,
) -> None:
    """Record one skill execution into 016's shared daily bucket.

    ⚠️ Not wired, by design: ``total_calls`` is already produced by 016's collector
    from the DSH event journal, so calling this for a normal execution would
    double-count. Use it only for the rich dimensions the journal lacks
    (``success`` / ``adopted`` / ``corrected``), and only after the collector stops
    writing those same fields.
    """
    if db is None:
        return
    key = {"main_id": tenant_id, "skill_key": skill_key, "date": (day or _today()).isoformat()}
    db[QUALITY_METRICS_COLLECTION].update_one(
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
