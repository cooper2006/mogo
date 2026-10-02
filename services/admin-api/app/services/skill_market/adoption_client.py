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

# The collection 011 writes the tenant-partitioned adoption state into.
ADOPTION_COLLECTION = "skill_adoption"
# The single shared marker key (must match 011 / 016 constants).
MARKED_LOW_QUALITY = "marked_low_quality"


async def fetch_marked_skill_keys(db: Any, *, main_id: str) -> set[str]:
    """Return the set of skill keys in ``main_id`` flagged ``marked_low_quality``.

    Reads the 011-owned ``skill_adoption`` collection. Skills that have no
    adoption row (the common case) are simply absent and treated as healthy.
    """
    if db is None:
        return set()
    rows = (
        await db[ADOPTION_COLLECTION]
        .find(
            {"tenant_id": main_id, MARKED_LOW_QUALITY: True},
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
