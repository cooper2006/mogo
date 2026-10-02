"""chat-api → 016 shared skill-quality metric writer (016 FR-3 data source).

011/chat-api is where skills actually execute, so it owns the *write* side of the
016 effect-score metrics. The collection name is shared with admin-api's
``skill_market.quality_metrics`` module over the same MongoDB instance (the
"one shared marker, no double-write" pattern already used by ``skill_adoption``).

The production call sites that feed real ``success`` / ``adopted`` / ``corrected``
signals are still a platform-level collection gap (mirroring 011's own
``AdoptionStore.record_adoption`` which is likewise not yet wired to a live event
stream). This module provides the ready-to-call entry point; wiring it into the
execution path is tracked separately.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

# Must match admin-api ``skill_market.quality_metrics.QUALITY_METRICS_COLLECTION``.
QUALITY_METRICS_COLLECTION = "skill_quality_metrics"


def _today(ts: Optional[datetime] = None) -> date:
    return (ts or datetime.now(timezone.utc)).date()


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

    chat-api calls this from the skill execution path; 016's ``SkillQualityScanner``
    later rolls the buckets up and writes the aggregated ``marked_low_quality`` bit.
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
