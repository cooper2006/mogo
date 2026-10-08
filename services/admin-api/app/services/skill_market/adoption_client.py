"""Read the 011 low-adoption marker back into the 016 market (T014-3 / T015-2).

011 (chat-api) persists the shared ``marked_low_quality`` bit into the
tenant-partitioned ``skill_adoption`` collection. This module is the 016
(admin-api) side of that shared bit: it reads which skills in a tenant are
flagged so the market list can down-rank (but still show) them.

Both services default to the same MongoDB instance (``MONGODB_URI`` /
``MONGODB_DB``), so reading the collection directly — rather than over an HTTP
call — is the intended design (the spec's "one shared marker, no double-write").
"""

from __future__ import annotations

from typing import Any

from app.services.skill_market.scoring import (
    LOW_QUALITY_MARKER,
    compute_effect_score,
    is_low_quality,
)

# The collection 011 writes the tenant-partitioned adoption state into.
ADOPTION_COLLECTION = "skill_adoption"
# The single *aggregated* marker key (must match 011 / 016 constants).
MARKED_LOW_QUALITY = "marked_low_quality"
# Independent source bits. The aggregated ``marked_low_quality`` is the OR of the
# two source bits so 011 (low adoption) and 016 (low effect score) can each flag
# a skill for down-ranking without either side's restore wiping the other's mark.
SOURCE_011_ADOPTION = "flagged_by_011_adoption"
SOURCE_016_QUALITY = "flagged_by_016_quality"

# The 016 side must use the same aggregated marker key as 011's deprecation store.
assert MARKED_LOW_QUALITY == LOW_QUALITY_MARKER, "016/011 marker key drift"


async def fetch_marked_skill_keys(db: Any, *, tenant_id: str) -> set[str]:
    """Return the set of skill keys in ``main_id`` flagged ``marked_low_quality``.

    Reads the 011-owned ``skill_adoption`` collection. Skills that have no
    adoption row (the common case) are simply absent and treated as healthy.
    """
    if db is None:
        return set()
    rows = (
        await db[ADOPTION_COLLECTION]
        .find(
            {"tenant_id": tenant_id, MARKED_LOW_QUALITY: True},
            {"skill_key": 1, "_id": 0},
        )
        .to_list(length=5000)
    )
    return {str(row.get("skill_key") or "") for row in rows if row.get("skill_key")}


def apply_low_quality_ranking(
    skills: list[dict[str, Any]],
    *,
    marked: set[str],
) -> list[dict[str, Any]]:
    """Annotate + down-rank flagged skills (016 FR-6: visible, sorted last).

    Each skill gets a ``markedLowQuality`` boolean; flagged skills are moved to
    the end of the list so they are still searchable but de-prioritised in the
    default market ordering. ``marked_low_quality`` behaviour is therefore
    falsifiable end-to-end: 011 marks -> 016 reads -> list reflects it.
    """
    annotated: list[dict[str, Any]] = []
    lowered: list[dict[str, Any]] = []
    for skill in skills:
        skill_id = str(skill.get("id") or "")
        is_marked = skill_id in marked
        if is_marked:
            skill["markedLowQuality"] = True
            lowered.append(skill)
        else:
            skill["markedLowQuality"] = False
            annotated.append(skill)
    return annotated + lowered


def _doc_key(tenant_id: str, skill_key: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "skill_key": skill_key}


async def apply_quality_assessment(
    db: Any,
    *,
    tenant_id: str,
    skill_key: str,
    total_calls: int,
    successful_calls: int,
    adopted_calls: int,
    corrected_calls: int,
    sustained_days: int,
) -> dict[str, Any]:
    """016 FR-3/FR-6: score a skill and persist the result into ``skill_adoption``.

    Closes the 016-side write loop: the aggregated ``marked_low_quality`` bit is
    the OR of 011's and 016's independent source bits, so a 016 quality mark
    survives an 011-side restore (and vice-versa). When the score is healthy the
    016 source bit is cleared and the aggregated bit is recomputed from the
    surviving 011 bit.
    """
    if db is None:
        return {"skill_key": skill_key, "marked_low_quality": False, "persisted": False}
    effect = compute_effect_score(
        total_calls=total_calls,
        successful_calls=successful_calls,
        adopted_calls=adopted_calls,
        corrected_calls=corrected_calls,
    )
    should_mark = is_low_quality(score=effect.score, sustained_days=sustained_days)
    if should_mark:
        await db[ADOPTION_COLLECTION].update_one(
            _doc_key(tenant_id, skill_key),
            {
                "$set": {SOURCE_016_QUALITY: True, MARKED_LOW_QUALITY: True},
                "$setOnInsert": {SOURCE_011_ADOPTION: False},
            },
            upsert=True,
        )
    else:
        await db[ADOPTION_COLLECTION].update_one(
            _doc_key(tenant_id, skill_key),
            [
                {
                    "$set": {
                        SOURCE_016_QUALITY: False,
                        MARKED_LOW_QUALITY: {"$or": [f"${SOURCE_011_ADOPTION}", False]},
                    }
                }
            ],
            upsert=True,
        )
    return {
        "skill_key": skill_key,
        "effect_score": round(effect.score, 4),
        "marked_low_quality": should_mark,
        "persisted": True,
    }


async def restore_quality(
    db: Any,
    *,
    tenant_id: str,
    skill_key: str,
    actor: str = "",
) -> dict[str, Any]:
    """016 FR-11: manually restore a skill's market ranking.

    Clears only the 016 source bit and recomputes the aggregated bit, so an
    011-side low-adoption mark (if any) is preserved.
    """
    if db is None:
        return {"skill_key": skill_key, "restored": False, "marked_low_quality": False}
    await db[ADOPTION_COLLECTION].update_one(
        _doc_key(tenant_id, skill_key),
        [
            {
                "$set": {
                    SOURCE_016_QUALITY: False,
                    MARKED_LOW_QUALITY: {"$or": [f"${SOURCE_011_ADOPTION}", False]},
                }
            }
        ],
        upsert=True,
    )
    return {
        "skill_key": skill_key,
        "restored": True,
        "actor": actor,
        "ranking": "normal",
    }

