"""Memory tenant adapter (021 first tenant = 017 memory).

Resolves a ``mogo://memory/<scope>/<owner>/<id>/[L0|L1|L2]`` address: it loads the
memory from the 017 store, delegates visibility to 017 ``visible_to`` (never
re-implementing auth), and returns the requested tier (L0 summary / L1 overview
/ L2 raw). Provenance (``source_session_id`` / ``source_type``) rides along in
``meta`` for the 021 trace and the future ``mogo://session/...`` root.
"""

from __future__ import annotations

from typing import Optional

from app.context_space.adapters.base import ResolvedTier, TierAdapter
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
    ViewerContext,
    check_visibility,
)
from app.memory.address import MemoryAddress, parse_memory_uri
from app.memory.store import MemoryStore


class MemoryTierAdapter(TierAdapter):
    """Resolves memory addresses against the 017 store (FR-18 / 021)."""

    root = "memory"

    async def resolve(
        self,
        *,
        uri: str,
        tier: Optional[str],
        tenant_id: str,
        viewer: ViewerContext,
    ) -> ResolvedTier:
        addr = parse_memory_uri(uri)
        if tier:
            addr = addr.with_tier(tier)

        store = MemoryStore()
        memory = await store.get(tenant_id=tenant_id, memory_id=addr.memory_id)
        if memory is None:
            raise ContextNotFoundError(f"memory not found: {addr.memory_id}")

        # Authorize against the **stored** record, never the caller-supplied URI
        # (R3 audit, 2026-10-06): the URI's scope/owner are attacker-controlled.
        if not check_visibility(addr=addr, ctx=viewer, memory=memory):
            raise ContextVisibilityError(f"viewer may not resolve {uri}")

        content = _select_tier(memory, addr.tier)
        return ResolvedTier(
            uri=addr.uri(),
            tier_used=addr.tier,
            content=content,
            meta={
                "memory_id": memory.memory_id,
                "scope": memory.scope,
                "l0_summary": memory.l0_summary,
                "l1_overview": memory.l1_overview,
                "tierable": memory.tierable,
                "source_session_id": memory.source_session_id,
                "source_type": memory.source_type,
                "created_at": memory.created_at,
            },
        )


def _select_tier(memory, tier: str) -> str:
    """Pick the content for the requested tier (FR-14)."""
    if tier == "L0":
        return memory.l0_summary or memory.content
    if tier == "L1":
        return memory.l1_overview or memory.l0_summary or memory.content
    # L2 (default): the raw detail.
    return memory.content


__all__ = ["MemoryTierAdapter"]
