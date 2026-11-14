"""036 T018: FR-014 "L1 assets are owner-only" visibility filter for the skill routes.

The rating layer already implements the predicate in ``ratings.list_ratings``
(level == L1 is visible only to ``owner_id`` / ``created_by``); the skill catalogue
and detail routes were not passing a viewer into it. This module reuses the shared
``trust_ratings`` collection with the exact same predicate so catalogue / market /
direct-read paths never leak unvetted L1 skills to unrelated callers, while leaving
``skills.py`` main list/pagination semantics untouched (non-invasive filter).
"""

from __future__ import annotations

from typing import Any

from app.services.trust_rating.ratings import (
    DEFAULT_TRUST_LEVEL,
    RATINGS_COLLECTION,
)


SKILL_ASSET_TYPE = "skill"


class L1SkillNotVisible(Exception):
    """Raised when a caller tries to directly read a skill rated L1 they do not own."""


def _viewer_id(current_user: dict[str, Any]) -> str:
    return str(current_user.get("_id") or current_user.get("id") or "")


def _owns(row: dict[str, Any], viewer: str) -> bool:
    if not viewer:
        return False
    return viewer in {str(row.get("owner_id") or ""), str(row.get("created_by") or "")}


async def hidden_l1_skill_ids(
    db: Any,
    *,
    tenant_id: str,
    viewer_id: str,
) -> set[str]:
    """Skill keys rated L1 that ``viewer_id`` must not see (FR-014).

    ``viewer_id`` empty means internal/management view -> nothing is hidden.
    """
    viewer = str(viewer_id or "")
    if not viewer:
        return set()
    rows = await db[RATINGS_COLLECTION].find(
        {
            "tenant_id": str(tenant_id),
            "asset_type": SKILL_ASSET_TYPE,
            "level": DEFAULT_TRUST_LEVEL,
        }
    ).to_list(length=10000)
    hidden: set[str] = set()
    for row in rows:
        if _owns(row, viewer):
            continue
        key = str(row.get("asset_key") or "")
        if key:
            hidden.add(key)
    return hidden


async def assert_skill_visible(
    db: Any,
    *,
    tenant_id: str,
    viewer_id: str,
    skill_key: str,
) -> None:
    """Raise ``L1SkillNotVisible`` for a direct read of an L1 skill not owned by viewer."""
    viewer = str(viewer_id or "")
    if not viewer:
        return
    row = await db[RATINGS_COLLECTION].find_one(
        {
            "tenant_id": str(tenant_id),
            "asset_type": SKILL_ASSET_TYPE,
            "asset_key": str(skill_key),
        }
    )
    if not row or row.get("level") != DEFAULT_TRUST_LEVEL:
        return
    if _owns(row, viewer):
        return
    raise L1SkillNotVisible(skill_key)