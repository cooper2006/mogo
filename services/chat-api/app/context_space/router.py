"""Unified context router (021).

The single entry point of the address space. It parses a ``mogo://`` URI,
dispatches to the correct tenant adapter, and wraps the resolution in a unified
retrieval trace (017 FR-17). Visibility is delegated to each backend; invisible
addresses raise rather than leaking data.

All four roots are wired here — the address space is storage-free: routing +
adapters + delegated visibility, no new database.
"""

from __future__ import annotations

from typing import Optional

from app.context_space.adapters.base import ResolvedTier, TierAdapter
from app.context_space.adapters.memory import MemoryTierAdapter
from app.context_space.adapters.resource import ResourceTierAdapter
from app.context_space.adapters.session import SessionTierAdapter
from app.context_space.adapters.skill import SkillTierAdapter
from app.context_space.address import parse_context_uri
from app.context_space.trace import build_trace, candidate_entry, skipped_entry
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
    ViewerContext,
)

# Tenant → adapter. Every root from spec 021 is wired:
#   memory  (017) · resource (005/014/015) · skill (004/018) · session (002).
_ADAPTERS: dict[str, TierAdapter] = {
    "memory": MemoryTierAdapter(),
    "resource": ResourceTierAdapter(),
    "skill": SkillTierAdapter(),
    "session": SessionTierAdapter(),
}

__all__ = [
    "ContextNotFoundError",
    "ContextVisibilityError",
    "resolve_memory",
]


async def resolve_memory(
    uri: str,
    *,
    tenant_id: str,
    viewer_id: str,
    viewer_role: str = "",
    is_workspace_member: bool = False,
    viewer_org_id: str = "",
    tier: Optional[str] = None,
    session_id: str = "",
    turn_id: str = "",
) -> dict:
    """Resolve a ``mogo://`` URI into tiered content + a retrieval trace (021).

    The name is retained for backward compatibility; the resolver now routes all
    four roots. Returns ``{"resolved": {...}, "trace": {...}}``. Raises
    :class:`ContextVisibilityError` for invisible addresses and
    :class:`ValueError` for unknown roots / malformed URIs.
    """
    if not uri.startswith("mogo://"):
        raise ValueError(f"not a mogo:// uri: {uri!r}")
    root = uri[len("mogo://"):].split("/", 1)[0]
    adapter = _ADAPTERS.get(root)
    if adapter is None:
        raise ValueError(f"unknown context root: {root!r}")

    # Validate the URI shape up front (parse_context_uri raises ValueError).
    parse_context_uri(uri)

    viewer = ViewerContext(
        viewer_id=viewer_id,
        viewer_role=viewer_role,
        is_workspace_member=is_workspace_member,
        tenant_id=tenant_id,
        viewer_org_id=viewer_org_id,
    )

    skipped: list[dict] = []
    try:
        resolved: ResolvedTier = await adapter.resolve(
            uri=uri, tier=tier, tenant_id=tenant_id, viewer=viewer
        )
    except ContextVisibilityError:
        skipped.append(skipped_entry(uri=uri, reason="visibility_denied"))
        build_trace([], skipped, session_id=session_id, turn_id=turn_id)
        raise
    except Exception as exc:  # context not found / parse error → trace + re-raise
        skipped.append(skipped_entry(uri=uri, reason=f"unresolved:{type(exc).__name__}"))
        build_trace([], skipped, session_id=session_id, turn_id=turn_id)
        raise

    candidate = candidate_entry(
        uri=resolved.uri,
        tier_used=resolved.tier_used,
        hit_reason="address_resolved",
        score=1.0,
    )
    trace = build_trace([candidate], skipped, session_id=session_id, turn_id=turn_id)
    return {"resolved": resolved.to_dict(), "trace": trace.to_dict()}
