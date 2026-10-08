"""In-memory + MongoDB-backed memory store (017 US1 / FR-5).

Memories are keyed by ``(tenant_id, memory_id)`` and tagged with a scope
(``personal`` / ``workspace`` / ``org``). The store itself is intentionally
simple — the scope/visibility logic lives in ``scope.py`` and the RAG
integration in ``retrieval.py``.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

import uuid
from typing import Any, Optional

from app.core.config import get_settings
from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.memory.scope import Memory, MemoryScope, visible_to
from app.memory.tiering import SUMMARY_REFRESH_DAYS_DEFAULT

COLLECTION = "memories"


class MemoryTooLargeError(ValueError):
    """Raised when non-tierable content exceeds the FR-16 hard byte limit."""


def _configured_refresh_days() -> int:
    """FR-15 staleness window, taken from configuration (falls back to default).

    ``MEMORY_SUMMARY_REFRESH_DAYS`` used to be a dead setting: operators could
    set it and nothing read it, so the hard-coded ``30`` always won (R3 audit,
    2026-10-06). This is now the single resolution point.
    """
    try:
        value = int(get_settings().MEMORY_SUMMARY_REFRESH_DAYS)
    except Exception as exc:
        log_print(f"[memory.store._configured_refresh_days] suppressed {type(exc).__name__}: {exc}", flush=True)
        return SUMMARY_REFRESH_DAYS_DEFAULT
    return value if value > 0 else SUMMARY_REFRESH_DAYS_DEFAULT


def _now_seconds() -> float:
    import time
    return time.time()


def _row_to_memory(row: dict[str, Any]) -> Memory:
    memory = Memory(
        memory_id=str(row.get("memory_id") or row.get("_id") or ""),
        content=str(row.get("content") or ""),
        scope=str(row.get("scope") or MemoryScope.PERSONAL.value),
        owner_id=str(row.get("owner_id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        created_at=float(row.get("created_at") or 0.0),
        last_accessed_at=float(row.get("last_accessed_at") or 0.0),
        l0_summary=str(row.get("l0_summary") or ""),
        l1_overview=str(row.get("l1_overview") or ""),
        l2_raw=str(row.get("l2_raw") or row.get("content") or ""),
        tierable=bool(row.get("tierable", True)),
        summary_generated_at=float(row.get("summary_generated_at") or 0.0),
        summary_refresh_days=int(row.get("summary_refresh_days") or _configured_refresh_days()),
        source_session_id=str(row.get("source_session_id") or ""),
        source_type=str(row.get("source_type") or ""),
    )
    memory.archived = bool(row.get("archived") or False)
    return memory


class MemoryStore:
    """Simple MongoDB-backed store for the three-scope memory layer."""

    async def save(
        self,
        *,
        content: str,
        owner_id: str,
        tenant_id: str,
        workspace_id: str = "",
        scope: str = MemoryScope.PERSONAL.value,
        memory_id: str = "",
        l0_summary: str = "",
        l1_overview: str = "",
        l2_raw: str = "",
        tierable: bool = True,
        summary_generated_at: float = 0.0,
        summary_refresh_days: int = 0,
        source_session_id: str = "",
        source_type: str = "",
    ) -> Memory:
        """Upsert a memory record. Returns the saved ``Memory``.

        Density tiers (FR-13) are persisted alongside the raw content. Non-
        tierable content that exceeds the FR-16 hard limit is rejected rather
        than silently truncated.

        Async because the backing store is ``AsyncIOMotorDatabase`` — the write
        must be awaited or the coroutine is discarded and nothing is persisted.
        """
        mem_id = str(memory_id or uuid.uuid4().hex)
        now = _now_seconds()
        # 0 / unset means "use the configured FR-15 window".
        summary_refresh_days = summary_refresh_days or _configured_refresh_days()
        # FR-16: layered-first, reject-only-as-fallback.
        # The limit is named ``..._BYTES`` and is compared against the *encoded*
        # size: ``len()`` counts characters, so CJK content (3 bytes/char) would
        # otherwise slip through at up to 3x the configured ceiling.
        hard_max = int(get_settings().MEMORY_L2_HARD_MAX_BYTES)
        content_bytes = len(content.encode("utf-8", errors="replace"))
        if not tierable and content_bytes > hard_max:
            raise MemoryTooLargeError(
                f"memory of {content_bytes} bytes is not tierable and exceeds the "
                f"hard limit of {hard_max} bytes; refuse to persist"
            )
        db = get_db()
        if db is None:
            return Memory(
                memory_id=mem_id,
                content=content,
                scope=scope,
                owner_id=owner_id,
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                created_at=now,
                last_accessed_at=now,
                l0_summary=l0_summary,
                l1_overview=l1_overview,
                l2_raw=l2_raw or content,
                tierable=tierable,
                summary_generated_at=summary_generated_at,
                summary_refresh_days=summary_refresh_days,
                source_session_id=source_session_id,
                source_type=source_type,
            )
        tenant_id = resolve_main_id(tenant_id)
        doc: dict[str, Any] = {
            "memory_id": mem_id,
            "content": content,
            "scope": scope,
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "created_at": now,
            "last_accessed_at": now,
            "l0_summary": l0_summary,
            "l1_overview": l1_overview,
            "l2_raw": l2_raw or content,
            "tierable": tierable,
            "summary_generated_at": summary_generated_at,
            "summary_refresh_days": summary_refresh_days,
            "source_session_id": source_session_id,
            "source_type": source_type,
        }
        await db[COLLECTION].replace_one(
            {"memory_id": mem_id, "tenant_id": tenant_id},
            doc,
            upsert=True,
        )
        return _row_to_memory(doc)

    async def list_for_viewer(
        self,
        *,
        tenant_id: str,
        viewer_id: str,
        viewer_role: str = "",
        is_workspace_member: bool = False,
        top_n: int = 20,
    ) -> list[Memory]:
        """Return memories visible to ``viewer_id`` within ``tenant_id``."""
        tenant_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return []
        # Pull all memories for the tenant; visibility is enforced in Python so
        # we do not leak org-scoped data across tenants.
        rows = await db[COLLECTION].find({"tenant_id": tenant_id}).to_list(length=500)
        from app.memory.retrieval import scope_filter
        memories = [_row_to_memory(r) for r in rows]
        filtered = scope_filter(
            memories,
            viewer_id=viewer_id,
            viewer_role=viewer_role,
            is_workspace_member=is_workspace_member,
        )
        # Sort: org > workspace > personal, then recency.
        weight = {
            MemoryScope.ORG.value: 3,
            MemoryScope.WORKSPACE.value: 2,
            MemoryScope.PERSONAL.value: 1,
        }
        filtered.sort(
            key=lambda m: (weight.get(m.scope, 0), m.last_accessed_at or 0),
            reverse=True,
        )
        return filtered[:top_n]

    async def get(self, *, tenant_id: str, memory_id: str) -> Optional[Memory]:
        """Fetch a single memory by id within a tenant. Returns None if absent."""
        tenant_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return None
        row = await db[COLLECTION].find_one({"memory_id": memory_id, "tenant_id": tenant_id})
        return _row_to_memory(row) if row else None

    async def delete(self, *, tenant_id: str, memory_id: str, owner_id: str) -> bool:
        """Delete a memory; returns True when one document was removed."""
        tenant_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return False
        result = await db[COLLECTION].delete_one({
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "owner_id": owner_id,
        })
        return result.deleted_count > 0


__all__ = ["COLLECTION", "MemoryStore", "MemoryTooLargeError"]
