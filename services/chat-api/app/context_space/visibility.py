"""Delegated visibility (021, OQ-10).

The address layer does **not** re-implement authorization. For each tenant it
delegates the visibility decision to the backend's *existing* check:

* ``memory``  → 017 ``visible_to(memory, MemoryViewerContext)`` (D4: the only
  predicate; the address layer merely forwards ``ViewerContext.memory_viewer``)
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
from typing import TYPE_CHECKING, Any, Optional

from app.context_space.address import (
    ASSET,
    ResourceAddress,
    SessionAddress,
    SkillAddress,
)
from app.infrastructure.observability.config import log_print
from app.memory.address import MemoryAddress

if TYPE_CHECKING:
    from app.memory.viewer import MemoryViewerContext


class ContextVisibilityError(PermissionError):
    """Raised when a viewer may not resolve an address (021 / 017 FR-2)."""


class ContextNotFoundError(LookupError):
    """Raised when an address does not resolve to any backend record (021)."""


@dataclass
class ViewerContext:
    """Who is asking to resolve an address (021).

    ``tenant_id`` / ``viewer_id`` are retained for the non-memory roots'
    coarse guards. Memory authorization is *never* decided here: it is
    delegated via ``memory_viewer`` to 017's ``visible_to``. A missing
    ``memory_viewer`` fails closed.
    """

    viewer_id: str = ""
    tenant_id: str = ""
    memory_viewer: Optional["MemoryViewerContext"] = None


def check_memory_visibility(
    *,
    addr: MemoryAddress,
    ctx: ViewerContext,
    memory: Optional[Any] = None,
) -> bool:
    """Delegate memory visibility to 017 ``visible_to`` (FR-2, no escalation).

    The address is a **locator, not a credential**. ``scope`` / ``owner_id`` in
    the URI are supplied by the caller and must never decide authorization:
    trusting them let any tenant member read any other member's memory by
    forging ``mogo://memory/personal/<self>/<victim_id>`` (R3 audit, 2026-10-06).

    Authorization therefore runs against the **stored record** loaded by the
    adapter and the server-built ``MemoryViewerContext``. Missing record or
    missing viewer → fail closed (B-4).
    """
    from app.memory.scope import visible_to

    if memory is None or ctx.memory_viewer is None:
        log_print(
            f"[context_space.visibility] deny {addr.uri()}: missing stored "
            f"record or memory_viewer; URI identity is not a credential",
            flush=True,
        )
        return False
    return visible_to(memory, ctx.memory_viewer)


def check_resource_visibility(*, addr: ResourceAddress, ctx: ViewerContext) -> bool:
    """Delegate to 005/014/015 tenant isolation (021).

    The backends already scope every query by ``tenant_id``; this guard verifies
    the requesting viewer's tenant matches the resource's owning tenant.
    """
    if not ctx.tenant_id:
        return True
    return addr.tenant_id == ctx.tenant_id


def check_skill_visibility(*, addr: SkillAddress, ctx: ViewerContext) -> bool:
    """Delegate to 004/018 org-scoped ownership (021)."""
    if addr.subtype == ASSET:
        return True
    if not ctx.tenant_id:
        return True
    return addr.identifiers[0] == ctx.tenant_id


def check_session_visibility(*, addr: SessionAddress, ctx: ViewerContext) -> bool:
    """Delegate to 002 participant set (021)."""
    if not ctx.tenant_id:
        return True
    return addr.tenant_id == ctx.tenant_id


def check_visibility(
    *,
    addr,
    ctx: Optional[ViewerContext] = None,
    viewer: Optional["MemoryViewerContext"] = None,
    memory: Optional[Any] = None,
) -> bool:
    """Dispatch delegated visibility by the address root (FR-18/021).

    Accepts either the router-built ``ctx: ViewerContext`` (which carries
    ``memory_viewer`` plus the coarse ``tenant_id`` / ``viewer_id``) or a
    server-built ``viewer: MemoryViewerContext`` directly, in which case a
    matching ``ViewerContext`` is constructed here. Memory authorization is
    always delegated via ``memory_viewer`` — never re-implemented.

    ``memory`` carries the **stored** 017 record for ``MemoryAddress``; it is
    required there so authorization never falls back to caller-supplied URI
    identity (see :func:`check_memory_visibility`).
    """
    if ctx is None:
        ctx = ViewerContext(
            viewer_id=str(getattr(viewer, "user_id", "") or ""),
            tenant_id=str(getattr(viewer, "tenant_id", "") or ""),
            memory_viewer=viewer,
        )
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
