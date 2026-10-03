"""Memory lifecycle: decay / cleanup (017 FR-8 / clarify OQ-2).

Decay period defaults to **30 days**; accessing a memory resets its timer. Once a
memory has been idle past the decay window it is eligible for cleanup (archival or
deletion, configurable).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_DECAY_DAYS = 30
SECONDS_PER_DAY = 86400

# Cleanup disposition once decayed (configurable).
CLEANUP_ARCHIVE = "archive"
CLEANUP_DELETE = "delete"


@dataclass
class MemoryLifecycle:
    """Configurable decay / cleanup policy."""

    decay_days: int = DEFAULT_DECAY_DAYS
    cleanup: str = CLEANUP_ARCHIVE

    @property
    def decay_seconds(self) -> float:
        return float(max(1, int(self.decay_days)) * SECONDS_PER_DAY)


def is_expired(
    *,
    last_accessed_at: float,
    now: float,
    lifecycle: MemoryLifecycle | None = None,
) -> bool:
    """Whether a memory has been idle past its decay window (FR-8)."""
    policy = lifecycle or MemoryLifecycle()
    return (now - float(last_accessed_at)) >= policy.decay_seconds


def seconds_until_expiry(
    *,
    last_accessed_at: float,
    now: float,
    lifecycle: MemoryLifecycle | None = None,
) -> float:
    """Seconds remaining before decay (negative once already expired)."""
    policy = lifecycle or MemoryLifecycle()
    return policy.decay_seconds - (now - float(last_accessed_at))


def touch(last_accessed_at: float, now: float) -> float:
    """Accessing a memory resets its decay timer (clarify OQ-2)."""
    return float(now)


# ---------------------------------------------------------------------------
# 017 FR-8 残项：老化清理（archival / deletion）
# ---------------------------------------------------------------------------

import time as _time


def _now_seconds() -> float:
    return _time.time()


def build_cleanup_query(
    *,
    now: float | None = None,
    lifecycle: MemoryLifecycle | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Build a MongoDB query matching memories whose decay window has elapsed
    (FR-8 archival / deletion eligibility).

    ``tenant_id`` narrows the sweep to a single tenant; omit for a global sweep.
    """
    policy = lifecycle or MemoryLifecycle()
    cutoff = float(now if now is not None else _now_seconds()) - policy.decay_seconds
    query: dict = {"last_accessed_at": {"$lt": cutoff}}
    if tenant_id:
        query["tenant_id"] = tenant_id
    return query


def clean_decayed_memories(
    *,
    db,
    lifecycle: MemoryLifecycle | None = None,
    tenant_id: str | None = None,
    now: float | None = None,
) -> dict:
    """Run the FR-8 decay sweep against the MongoDB ``memories`` collection.

    * ``cleanup == "delete"``  → removes the expired documents;
    * ``cleanup == "archive"`` → stamps ``archived=True`` (queryable, not dropped).

    Accepts either a synchronous pymongo-style db (unit tests) or the Motor
    async db used in production; the Motor path is returned as a coroutine
    and must be awaited by the caller.

    Returns ``{"removed": n, "archived": m, "cleanup": disposition}`` so the
    caller (scheduler / test) can audit the outcome.
    """
    from app.memory.store import COLLECTION

    policy = lifecycle or MemoryLifecycle()
    query = build_cleanup_query(now=now, lifecycle=policy, tenant_id=tenant_id)
    disposition = str(policy.cleanup or CLEANUP_ARCHIVE)

    collection = db[COLLECTION]

    # Motor (async) database → hand back the coroutine; the scheduler awaits it.
    if _is_motor_collection(collection):
        return {"_pending": _motor_sweep(collection, query, policy, disposition, tenant_id)}

    # Synchronous (pymongo / test fake) path.
    if disposition == CLEANUP_DELETE:
        result = collection.delete_many(query)
        removed = int(getattr(result, "deleted_count", 0) or 0)
        return {"removed": removed, "archived": 0, "cleanup": disposition}

    # Archive (default, non-destructive): stamp every un-archived decayed doc.
    from pymongo import UpdateOne

    cutoff = query["last_accessed_at"]["$lt"]
    tenant_filter = str(tenant_id) if tenant_id else None
    if tenant_filter is not None:
        rows = list(collection.find({
            "last_accessed_at": {"$lt": cutoff},
            "tenant_id": tenant_filter,
        }))
    else:
        rows = list(collection.find({"last_accessed_at": {"$lt": cutoff}}))
    stamps = [
        {"memory_id": r["memory_id"], "tenant_id": r.get("tenant_id", "")}
        for r in rows
        if not r.get("archived")
    ]
    ops = [
        UpdateOne(
            {"memory_id": s["memory_id"], "tenant_id": s["tenant_id"]},
            {"$set": {"archived": True, "archived_at": _now_seconds()}},
            upsert=False,
        )
        for s in stamps
    ]
    result = collection.bulk_write(ops) if ops else None
    archived = int(getattr(result, "modified_count", 0) or 0) if result is not None else 0
    return {"removed": 0, "archived": archived, "cleanup": disposition}


def _is_motor_collection(collection) -> bool:
    """Whether the collection is a Motor async collection (awaitable ops)."""
    import inspect
    find = getattr(collection, "find", None)
    if find is None:
        return False
    return inspect.iscoroutinefunction(find)


async def _motor_sweep(collection, query, policy, disposition: str, tenant_id: str | None) -> dict:
    """Motor variant of the sweep; awaited by the scheduler."""
    if disposition == CLEANUP_DELETE:
        result = await collection.delete_many(query)
        removed = int(getattr(result, "deleted_count", 0) or 0)
        return {"removed": removed, "archived": 0, "cleanup": disposition}

    from pymongo import UpdateOne

    cutoff = query["last_accessed_at"]["$lt"]
    tenant_filter = str(tenant_id) if tenant_id else None
    find_query: dict = {"last_accessed_at": {"$lt": cutoff}}
    if tenant_filter is not None:
        find_query["tenant_id"] = tenant_filter
    rows = await collection.find(find_query).to_list(length=None)
    stamps = [
        {"memory_id": r["memory_id"], "tenant_id": r.get("tenant_id", "")}
        for r in rows
        if not r.get("archived")
    ]
    ops = [
        UpdateOne(
            {"memory_id": s["memory_id"], "tenant_id": s["tenant_id"]},
            {"$set": {"archived": True, "archived_at": _now_seconds()}},
            upsert=False,
        )
        for s in stamps
    ]
    result = await collection.bulk_write(ops) if ops else None
    archived = int(getattr(result, "modified_count", 0) or 0) if result is not None else 0
    return {"removed": 0, "archived": archived, "cleanup": disposition}


__all__ = [
    "CLEANUP_ARCHIVE",
    "CLEANUP_DELETE",
    "DEFAULT_DECAY_DAYS",
    "MemoryLifecycle",
    "SECONDS_PER_DAY",
    "build_cleanup_query",
    "clean_decayed_memories",
    "is_expired",
    "seconds_until_expiry",
    "touch",
]
