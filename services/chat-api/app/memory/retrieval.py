"""Memory-in-RAG retrieval by scope (017 T010-T011 / US2).

Feeds memories into the RAG retrieval pass: a scope-filtered pre-filter keeps
only memories the viewer may read (017 FR-2 visibility, no privilege
escalation); the surviving records are ranked and returned as RAG candidates
so the retrieval pass can use them alongside knowledge chunks.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.memory.scope import Memory, MemoryScope, visible_to


def scope_filter(
    memories: Iterable[Memory],
    *,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
    only_scopes: Optional[tuple[str, ...]] = None,
) -> list[Memory]:
    """T010 — the pre-retrieval scope filter (按 scope 过滤).

    Returns only the memories the viewer may read. When ``only_scopes`` is
    given, further restricts to those scopes (e.g. a retrieval pass that only
    wants ``org`` + ``workspace``).
    """
    allowed = set(only_scopes or (MemoryScope.PERSONAL.value, MemoryScope.WORKSPACE.value, MemoryScope.ORG.value))
    survivors: list[Memory] = []
    for memory in memories:
        if memory.scope not in allowed:
            continue
        if visible_to(memory, viewer_id=viewer_id, viewer_role=viewer_role, is_workspace_member=is_workspace_member):
            survivors.append(memory)
    return survivors


def memory_rag_candidates(
    memories: Iterable[Memory],
    *,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
    top_n: int = 8,
    now: float = 0.0,
) -> list[dict[str, Any]]:
    """T010 — turn scope-filtered memories into ranked RAG candidates.

    Ranking: scope weight (org > workspace > personal), then recency of last
    access. The output is a list of ``{memory_id, scope, content, score}``
    dicts ready for the RAG retrieval pass.
    """
    scope_weight = {
        MemoryScope.ORG.value: 3,
        MemoryScope.WORKSPACE.value: 2,
        MemoryScope.PERSONAL.value: 1,
    }
    filtered = scope_filter(
        memories,
        viewer_id=viewer_id,
        viewer_role=viewer_role,
        is_workspace_member=is_workspace_member,
    )

    def _rank(memory: Memory) -> tuple[int, float]:
        weight = scope_weight.get(memory.scope, 0)
        recency = float(memory.last_accessed_at or 0)
        return weight, recency

    ranked = sorted(filtered, key=_rank, reverse=True)[: max(1, int(top_n))]
    return [
        {
            "memory_id": m.memory_id,
            "scope": m.scope,
            "content": m.content,
            "score": float(scope_weight.get(m.scope, 0)),
        }
        for m in ranked
    ]


def promoted_memories_retrievable(
    memories: Iterable[Memory],
    *,
    viewer_id: str,
    promoted_by: str = "",
    viewer_role: str = "",
) -> list[str]:
    """T011 — verify promoted (org-scope) memories are retrievable by the viewer.

    A memory promoted to ``org`` becomes readable by any tenant member
    (``visible_to`` returns True for a non-empty viewer within the tenant).
    This is the US2 upgrade-authorization + retrieval-filter acceptance.
    """
    result: list[str] = []
    for memory in memories:
        if memory.scope != MemoryScope.ORG.value:
            continue
        if visible_to(memory, viewer_id=viewer_id, viewer_role=viewer_role):
            result.append(memory.memory_id)
    return result


__all__ = [
    "memory_rag_candidates",
    "promoted_memories_retrievable",
    "scope_filter",
]
