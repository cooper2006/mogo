"""In-memory + MongoDB-backed memory store (017 US1 / FR-5).

Memories are keyed by ``(tenant_id, memory_id)`` and tagged with a scope
(``personal`` / ``workspace`` / ``org``). The store itself is intentionally
simple — the scope/visibility logic lives in ``scope.py`` and the RAG
integration in ``retrieval.py``.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.db import get_db
from app.core.tenant import resolve_main_id
from app.memory.scope import Memory, MemoryScope, visible_to

COLLECTION = "memories"


def _now_seconds() -> float:
    import time
    return time.time()


def _row_to_memory(row: dict[str, Any]) -> Memory:
    return Memory(
        memory_id=str(row.get("memory_id") or row.get("_id") or ""),
        content=str(row.get("content") or ""),
        scope=str(row.get("scope") or MemoryScope.PERSONAL.value),
        owner_id=str(row.get("owner_id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        tenant_id=str(row.get("tenant_id") or "default"),
        created_at=float(row.get("created_at") or 0.0),
        last_accessed_at=float(row.get("last_accessed_at") or 0.0),
    )


class MemoryStore:
    """Simple MongoDB-backed store for the three-scope memory layer."""

    def save(
        self,
        *,
        content: str,
        owner_id: str,
        tenant_id: str,
        workspace_id: str = "",
        scope: str = MemoryScope.PERSONAL.value,
        memory_id: str = "",
    ) -> Memory:
        """Upsert a memory record. Returns the saved ``Memory``."""
        mem_id = str(memory_id or uuid.uuid4().hex)
        now = _now_seconds()
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
            )
        main_id = resolve_main_id(tenant_id)
        doc: dict[str, Any] = {
            "memory_id": mem_id,
            "content": content,
            "scope": scope,
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "tenant_id": main_id,
            "created_at": now,
            "last_accessed_at": now,
        }
        db[COLLECTION].replace_one(
            {"memory_id": mem_id, "tenant_id": main_id},
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
        main_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return []
        # Pull all memories for the tenant; visibility is enforced in Python so
        # we do not leak org-scoped data across tenants.
        rows = await db[COLLECTION].find({"tenant_id": main_id}).to_list(length=500)
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
        main_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return None
        row = await db[COLLECTION].find_one({"memory_id": memory_id, "tenant_id": main_id})
        return _row_to_memory(row) if row else None

    async def delete(self, *, tenant_id: str, memory_id: str, owner_id: str) -> bool:
        """Delete a memory; returns True when one document was removed."""
        main_id = resolve_main_id(tenant_id)
        db = get_db()
        if db is None:
            return False
        result = await db[COLLECTION].delete_one({
            "memory_id": memory_id,
            "tenant_id": main_id,
            "owner_id": owner_id,
        })
        return result.deleted_count > 0


__all__ = ["MemoryStore", "COLLECTION"]
