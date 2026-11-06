"""Offboarding / deletion explicit invalidation (017 T037, H-3 / H-6).

When a user leaves (is offboarded or deleted) their memories must be **explicitly
invalidated** so they exit active retrieval:

* personal memories owned by the user (``owner_id == user_id``); and
* project memories the user *owns* (``project_owner_id == user_id`` — the N1
  disambiguator ties a project memory to its owner; a mere member leaving does
  not invalidate the owner's memory).

When a project is archived, its memories exit RAG default retrieval (H-6): while
``load_visible_project_keys`` already excludes archived projects from a member's
visible set, we additionally mark the memories ``invalidated`` so the fact is
explicit and auditable rather than implicit.

Invalidated memories stay structurally valid (so admin governance can still list
them, flagged) but are invisible to every normal viewer via
``scope.visible_to`` (a rejected/invalidated record is fail-closed there).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from app.core.db import get_db
from app.core.tenant import resolve_tenant_id
from app.memory.store import COLLECTION
from app.memory.scope import (
    PROMOTION_STATUS_NONE,
    PROMOTION_STATUS_REJECTED,
)


def _invalidation_set(now: float, *, reason: str) -> dict[str, Any]:
    return {
        "invalidated": True,
        "invalidated_at": now,
        "invalidated_reason": reason,
    }


async def invalidate_user_memories(
    tenant_id: str,
    user_id: str,
    *,
    reason: str = "owner_offboarded",
    db: Optional[Any] = None,
) -> int:
    """Mark a departed user's personal + owned-project memories as invalidated.

    Returns the number of memories modified. Safe to call with ``db=None`` (no-op
    returning 0) so callers in a DB-less context don't error.
    """
    db = db or get_db()
    if db is None or not tenant_id or not user_id:
        return 0
    tenant_id = resolve_tenant_id(tenant_id)
    now = time.time()
    # Scope the two legs to their own scopes (N1): a *personal* memory is owned by
    # ``owner_id``; a *project* memory is owned by ``project_owner_id`` (the pair
    # ``(project_id, project_owner_id)`` disambiguates duplicate project rows). A
    # departing member's contribution to someone else's project therefore survives.
    result = await db[COLLECTION].update_many(
        {
            "tenant_id": tenant_id,
            "archived": {"$ne": True},
            "invalidated": {"$ne": True},
            "$or": [
                {"scope": "personal", "owner_id": user_id},
                {"scope": "project", "project_owner_id": user_id},
            ],
        },
        {"$set": _invalidation_set(now, reason=reason)},
    )
    return int(getattr(result, "modified_count", 0) or 0)


async def invalidate_project_memories(
    tenant_id: str,
    project_id: str,
    project_owner_id: str,
    *,
    reason: str = "project_archived",
    db: Optional[Any] = None,
) -> int:
    """H-6: a project's memories exit RAG default retrieval when it is archived.

    Marks all active (non-archived, non-already-invalidated) project memories of
    ``(project_id, project_owner_id)`` as invalidated. Returns the count.
    """
    db = db or get_db()
    if db is None or not tenant_id or not project_id or not project_owner_id:
        return 0
    tenant_id = resolve_tenant_id(tenant_id)
    now = time.time()
    result = await db[COLLECTION].update_many(
        {
            "tenant_id": tenant_id,
            "scope": "project",
            "project_id": project_id,
            "project_owner_id": project_owner_id,
            "archived": {"$ne": True},
            "invalidated": {"$ne": True},
        },
        {"$set": _invalidation_set(now, reason=reason)},
    )
    return int(getattr(result, "modified_count", 0) or 0)


async def restore_user_memories(
    tenant_id: str,
    user_id: str,
    *,
    db: Optional[Any] = None,
) -> int:
    """Undo :func:`invalidate_user_memories` (e.g. offboarding was reversed).

    Re-validates only memories that were invalidated for this user, leaving
    memories invalidated for other reasons untouched.
    """
    db = db or get_db()
    if db is None or not tenant_id or not user_id:
        return 0
    tenant_id = resolve_tenant_id(tenant_id)
    result = await db[COLLECTION].update_many(
        {
            "tenant_id": tenant_id,
            "invalidated": True,
            "invalidated_reason": "owner_offboarded",
            "$or": [
                {"scope": "personal", "owner_id": user_id},
                {"scope": "project", "project_owner_id": user_id},
            ],
        },
        {
            "$set": {"invalidated": False},
            "$unset": {
                "invalidated_at": "",
                "invalidated_reason": "",
            },
        },
    )
    return int(getattr(result, "modified_count", 0) or 0)


def is_effectively_invisible(promotion_status: str) -> bool:
    """A rejected promotion carries no visibility consequence (scope unchanged).

    Reserved helper: only ``approved`` mutates scope. Kept to document that the
    promotion state machine itself never hides a memory — visibility is governed
    by ``scope`` + ``invalidated`` + ``archived`` in :func:`scope.visible_to`.
    """
    return promotion_status not in (
        PROMOTION_STATUS_NONE,
        PROMOTION_STATUS_PENDING,
        PROMOTION_STATUS_APPROVED,
        PROMOTION_STATUS_REJECTED,
    )


__all__ = [
    "invalidate_project_memories",
    "invalidate_user_memories",
    "restore_user_memories",
]
