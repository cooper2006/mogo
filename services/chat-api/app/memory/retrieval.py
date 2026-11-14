"""Memory-in-RAG retrieval by scope (017 T010-T011 / US2).

Feeds memories into the RAG retrieval pass: a scope-filtered pre-filter keeps
only memories the viewer may read (017 FR-2 visibility, no privilege
escalation); the surviving records are ranked and returned as RAG candidates
so the retrieval pass can use them alongside knowledge chunks.

D4: every entry point takes a single server-built ``MemoryViewerContext``.
The scattered ``viewer_id`` / ``viewer_role`` / ``is_workspace_member`` /
``viewer_org_id`` kwargs are gone; ``visible_to(memory, viewer)`` is the only
visibility predicate.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.context_space.trace import build_trace, candidate_entry, skipped_entry
from app.memory.address import MemoryAddress
from app.memory.scope import (
    DEFAULT_PROJECT_ID,
    Memory,
    MemoryScope,
    visible_to,
)
from app.memory.viewer import MemoryViewerContext

#: Ranking weight: department > project > personal (D4).
SCOPE_WEIGHT: dict[str, int] = {
    MemoryScope.DEPARTMENT.value: 3,
    MemoryScope.PROJECT.value: 2,
    MemoryScope.PERSONAL.value: 1,
}

_VALID_SCOPES = frozenset(SCOPE_WEIGHT)


def _row_archived(memory: Memory) -> bool:
    """Whether the memory has been archived by the FR-8 decay sweep."""
    return bool(getattr(memory, "archived", False))


def _memory_uri(memory: Memory, tier: str = "L0") -> str:
    """Address of a (possibly filtered-out) memory, for trace entries."""
    return MemoryAddress(
        scope=memory.scope,
        owner_id=memory.owner_id,
        memory_id=memory.memory_id,
        tier=tier,
    ).uri()


def _skip_reason(memory: Memory) -> str:
    """F-3: classify *why* a memory was filtered out (priority ordered).

    Reasons are deliberately disjoint so a trace can be aggregated:
    ``archived`` / ``unknown_scope`` / ``default_project_excluded`` /
    ``missing_project_owner`` / ``scope_invisible``.
    """
    if _row_archived(memory):
        return "archived"
    scope = str(memory.scope or "")
    if scope not in _VALID_SCOPES:
        return "unknown_scope"
    if scope == MemoryScope.PROJECT.value:
        if str(memory.project_id or "") == DEFAULT_PROJECT_ID:
            return "default_project_excluded"
        if not str(memory.project_owner_id or ""):
            return "missing_project_owner"
    return "scope_invisible"


def scope_filter(
    memories: Iterable[Memory],
    *,
    viewer: MemoryViewerContext,
    only_scopes: Optional[tuple[str, ...]] = None,
) -> list[Memory]:
    """T010 — the pre-retrieval scope filter (按 scope 过滤).

    Returns only the memories ``viewer`` may read, via ``visible_to``. When
    ``only_scopes`` is given, further restricts to those scopes.
    """
    allowed = set(only_scopes or _VALID_SCOPES)
    survivors: list[Memory] = []
    for memory in memories:
        if memory.scope not in allowed:
            continue
        if _row_archived(memory):
            continue
        if visible_to(memory, viewer):
            survivors.append(memory)
    return survivors


def _rank(memory: Memory) -> tuple[int, float]:
    return SCOPE_WEIGHT.get(memory.scope, 0), float(memory.last_accessed_at or 0)


def memory_rag_candidates(
    memories: Iterable[Memory],
    *,
    viewer: MemoryViewerContext,
    top_n: int = 8,
    now: float = 0.0,
    include_tier: str = "L2",
) -> list[dict]:
    """T010 — turn scope-filtered memories into ranked RAG candidates.

    Ranking: scope weight (department > project > personal), then recency of
    last access. ``include_tier`` (FR-14) selects L0 / L1 / L2 detail.
    """
    filtered = scope_filter(memories, viewer=viewer)
    ranked = sorted(filtered, key=_rank, reverse=True)[: max(1, int(top_n))]
    return [
        {
            "memory_id": m.memory_id,
            "scope": m.scope,
            "content": _select_tier(m, include_tier),
            "l0_summary": m.l0_summary,
            "l1_overview": m.l1_overview,
            "tier": include_tier,
            "addr": _memory_uri(m, include_tier),
            "score": float(SCOPE_WEIGHT.get(m.scope, 0)),
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
    viewer: MemoryViewerContext,
    include_tier: str = "L1",
    top_n: int = 8,
    now: float = 0.0,
    session_id: str = "",
    turn_id: str = "",
) -> tuple[list[dict], dict]:
    """FR-14 / FR-17 — progressive retrieval with a unified trace.

    Loads only ``include_tier`` content by default (L0→L1→L2 on demand) and
    returns ``(candidates, trace)``. F-3: every memory that fails the scope
    filter produces a ``skipped_entry`` with a classifiable ``reason``; the
    trace's ``skipped`` list is therefore non-empty whenever anything was
    filtered out.
    """
    all_memories = list(memories)
    filtered = scope_filter(all_memories, viewer=viewer)
    ranked = sorted(filtered, key=_rank, reverse=True)[: max(1, int(top_n))]

    candidates: list[dict] = []
    for memory in ranked:
        candidates.append({
            "memory_id": memory.memory_id,
            "scope": memory.scope,
            "tier_used": include_tier,
            "content": _select_tier(memory, include_tier),
            "l0_summary": memory.l0_summary,
            "l1_overview": memory.l1_overview,
            "addr": _memory_uri(memory, include_tier),
            "score": float(SCOPE_WEIGHT.get(memory.scope, 0)),
        })

    # F-3: classify each filtered-out memory (identity comparison so records
    # dropped by the top_n cut on *visible* memories are not mislabelled).
    visible_ids = {id(m) for m in filtered}
    skipped = [
        skipped_entry(uri=_memory_uri(m), reason=_skip_reason(m))
        for m in all_memories
        if id(m) not in visible_ids
    ]

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
        skipped,
        session_id=session_id,
        turn_id=turn_id,
    )
    return candidates, trace.to_dict()


def promoted_memories_retrievable(
    memories: Iterable[Memory],
    *,
    viewer: MemoryViewerContext,
) -> list[str]:
    """T011 — verify promoted ``department`` memories are retrievable.

    A memory promoted to ``department`` becomes readable by viewers whose
    ``visible_department_ids`` contains ``memory.department_id`` (or by a
    full-access admin). ``visible_to`` remains the single predicate.
    """
    result: list[str] = []
    for memory in memories:
        if memory.scope != MemoryScope.DEPARTMENT.value:
            continue
        if visible_to(memory, viewer):
            result.append(memory.memory_id)
    return result


__all__ = [
    "SCOPE_WEIGHT",
    "memory_rag_candidates",
    "progressive_memory_retrieval",
    "promoted_memories_retrievable",
    "scope_filter",
]
