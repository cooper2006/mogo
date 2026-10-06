"""Memory-in-RAG retrieval by scope (017 T010-T011 / US2).

Feeds memories into the RAG retrieval pass: a scope-filtered pre-filter keeps
only memories the viewer may read (017 FR-2 visibility, no privilege
escalation); the surviving records are ranked and returned as RAG candidates
so the retrieval pass can use them alongside knowledge chunks.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.context_space.trace import build_trace, candidate_entry, skipped_entry
from app.memory.scope import Memory, MemoryScope, visible_to
from app.memory.address import MemoryAddress


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
        # FR-8 decayed + archived memories are no longer RAG candidates.
        if _row_archived(memory):
            continue
        if visible_to(memory, viewer_id=viewer_id, viewer_role=viewer_role, is_workspace_member=is_workspace_member):
            survivors.append(memory)
    return survivors


def _row_archived(memory: Memory) -> bool:
    """Whether the memory has been archived by the FR-8 decay sweep."""
    return bool(getattr(memory, "archived", False))


def memory_rag_candidates(
    memories: Iterable[Memory],
    *,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
    top_n: int = 8,
    now: float = 0.0,
    include_tier: str = "L2",
) -> list[dict[str, Any]]:
    """T010 — turn scope-filtered memories into ranked RAG candidates.

    Ranking: scope weight (org > workspace > personal), then recency of last
    access. The output is a list of ``{memory_id, scope, content, score, ...}``
    dicts ready for the RAG retrieval pass.

    ``include_tier`` (FR-14) selects how much detail is injected: ``L0`` summary,
    ``L1`` overview, or ``L2`` raw (the legacy default, unchanged behavior).
    Tier summaries are always attached so the caller may drill down on demand.
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
            "content": _select_tier(m, include_tier),
            "l0_summary": m.l0_summary,
            "l1_overview": m.l1_overview,
            "tier": include_tier,
            "addr": MemoryAddress(
                scope=m.scope, owner_id=m.owner_id, memory_id=m.memory_id, tier=include_tier
            ).uri(),
            "score": float(scope_weight.get(m.scope, 0)),
        }
        for m in ranked
    ]


def _select_tier(memory: Memory, tier: str) -> str:
    """Pick the content string for a requested tier (FR-14)."""
    if tier == "L0":
        return memory.l0_summary or memory.content
    if tier == "L1":
        return memory.l1_overview or memory.l0_summary or memory.content
    return memory.content


def progressive_memory_retrieval(
    memories: Iterable[Memory],
    *,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
    include_tier: str = "L1",
    top_n: int = 8,
    now: float = 0.0,
    session_id: str = "",
    turn_id: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """FR-14 / FR-17 — progressive retrieval with a unified trace.

    Loads only ``include_tier`` content by default (L0→L1→L2 on demand) and
    returns ``(candidates, trace)``. The trace records which memories were
    surfaced, the tier used, and the hit reason, bound to ``session_id`` /
    ``turn_id`` for replay.
    """
    scope_weight = {
        MemoryScope.ORG.value: 3,
        MemoryScope.WORKSPACE.value: 2,
        MemoryScope.PERSONAL.value: 1,
    }

    def _rank(memory: Memory) -> tuple[int, float]:
        return scope_weight.get(memory.scope, 0), float(memory.last_accessed_at or 0)

    filtered = scope_filter(
        memories,
        viewer_id=viewer_id,
        viewer_role=viewer_role,
        is_workspace_member=is_workspace_member,
    )
    ranked = sorted(filtered, key=_rank, reverse=True)[: max(1, int(top_n))]

    candidates: list[dict[str, Any]] = []
    for memory in ranked:
        content = _select_tier(memory, include_tier)
        addr = MemoryAddress(
            scope=memory.scope,
            owner_id=memory.owner_id,
            memory_id=memory.memory_id,
            tier=include_tier,
        ).uri()
        candidates.append({
            "memory_id": memory.memory_id,
            "scope": memory.scope,
            "tier_used": include_tier,
            "content": content,
            "l0_summary": memory.l0_summary,
            "l1_overview": memory.l1_overview,
            "addr": addr,
            "score": float(scope_weight.get(memory.scope, 0)),
        })
    trace = build_trace(
        [
            candidate_entry(
                uri=c["addr"],
                tier_used=c["tier_used"],
                hit_reason="scope_visible_ranked",
                score=c["score"],
            )
            for c in candidates
        ],
        [],
        session_id=session_id,
        turn_id=turn_id,
    )
    return candidates, trace.to_dict()


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
    "progressive_memory_retrieval",
    "promoted_memories_retrievable",
    "scope_filter",
]
