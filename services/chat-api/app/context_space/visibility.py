"""Delegated visibility (021, OQ-10).

The address layer does **not** re-implement authorization. For each tenant it
delegates the visibility decision to the backend's *existing* check:

* ``memory``  → 017 ``visible_to`` (personal/workspace/org)
* ``resource`` → 005 / 014 / 015 tenant isolation (the backend query already
  scopes by ``tenant_id``; this is the address-layer coarse guard)
* ``skill``   → 004 / 018 org-scoped ownership (+ ``a2a_exposed`` left to backend)
* ``session`` → 002 participant set (tenant match is the coarse guard; the
  backend further restricts personal sessions to their owner)

Invisible candidates are silently trimmed (never error), preserving 017's
"no privilege escalation" guarantee and avoiding a new escalation surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.context_space.address import (
    ASSET,
    ResourceAddress,
    SessionAddress,
    SkillAddress,
)
from app.infrastructure.observability.config import log_print
from app.memory.address import MemoryAddress


class ContextVisibilityError(PermissionError):
    """Raised when a viewer may not resolve an address (021 / 017 FR-2)."""


class ContextNotFoundError(LookupError):
    """Raised when an address does not resolve to any backend record (021)."""


@dataclass
class ViewerContext:
    """Who is asking to resolve an address (021)."""

    viewer_id: str
    viewer_role: str = ""
    is_workspace_member: bool = False
    tenant_id: str = ""


def check_memory_visibility(
    *,
    addr: MemoryAddress,
    ctx: ViewerContext,
    memory: Optional[Any] = None,
) -> bool:
    """Delegate visibility to 017 ``visible_to`` (FR-2, no escalation).

    The address is a **locator, not a credential**. ``scope`` / ``owner_id`` in
    the URI are supplied by the caller and must never decide authorization:
    trusting them let any tenant member read any other member's memory by
    forging ``mogo://memory/personal/<self>/<victim_id>`` (R3 audit, 2026-10-06).

    Authorization therefore runs against the **stored record** loaded by the
    adapter. When no record is supplied we fail closed — the URI alone cannot
    prove ownership.
    """
    from app.memory.scope import visible_to

    if memory is None:
        log_print(
            f"[context_space.visibility] deny {addr.uri()}: no stored record "
            f"supplied; URI identity is not a credential",
            flush=True,
        )
        return False
    return visible_to(
        memory,
        viewer_id=ctx.viewer_id,
        viewer_role=ctx.viewer_role,
        is_workspace_member=ctx.is_workspace_member,
    )


def check_resource_visibility(*, addr: ResourceAddress, ctx: ViewerContext) -> bool:
    """Delegate to 005/014/015 tenant isolation (021).

    The backends already scope every query by ``tenant_id``; this guard verifies
    the requesting viewer's tenant matches the resource's owning tenant. Org-wide
    resources (``tenant_id`` shared) pass; a mismatch is silently rejected.
    """
    if not ctx.tenant_id:
        # No tenant context → treat as the owning tenant (best-effort, non-fatal).
        return True
    return addr.tenant_id == ctx.tenant_id


def check_skill_visibility(*, addr: SkillAddress, ctx: ViewerContext) -> bool:
    """Delegate to 004/018 org-scoped ownership (021).

    For a 004 Skill, ``identifiers[0]`` is the owning org/tenant. For a 018 asset
    the address carries no tenant, so exposure is deferred to the asset's own
    governance (``a2a_exposed`` / status) — the address layer does not block it.
    """
    if addr.subtype == ASSET:
        return True
    if not ctx.tenant_id:
        return True
    return addr.identifiers[0] == ctx.tenant_id


def check_session_visibility(*, addr: SessionAddress, ctx: ViewerContext) -> bool:
    """Delegate to 002 participant set (021).

    The coarse guard is tenant match; the backend load further restricts personal
    sessions to their owner and co-presence sessions to participants.
    """
    if not ctx.tenant_id:
        return True
    return addr.tenant_id == ctx.tenant_id


def check_visibility(*, addr, ctx: ViewerContext, memory: Optional[Any] = None) -> bool:
    """Dispatch delegated visibility by the address root (FR-18/021).

    ``memory`` carries the **stored** 017 record for ``MemoryAddress``; it is
    required there so authorization never falls back to caller-supplied URI
    identity (see :func:`check_memory_visibility`).
    """
    if isinstance(addr, MemoryAddress):
        return check_memory_visibility(addr=addr, ctx=ctx, memory=memory)
    if isinstance(addr, ResourceAddress):
        return check_resource_visibility(addr=addr, ctx=ctx)
    if isinstance(addr, SkillAddress):
        return check_skill_visibility(addr=addr, ctx=ctx)
    if isinstance(addr, SessionAddress):
        return check_session_visibility(addr=addr, ctx=ctx)
    raise NotImplementedError(f"no visibility check for {type(addr).__name__}")


__all__ = [
    "ViewerContext",
    "check_memory_visibility",
    "check_resource_visibility",
    "check_skill_visibility",
    "check_session_visibility",
    "check_visibility",
]
