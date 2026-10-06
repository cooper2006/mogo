"""Unified context-address endpoints (021).

Exposes the ``mogo://`` address space over HTTP so the router is reachable from
production, not only from tests. Without this the whole 021 layer (router +
four tenant adapters + delegated visibility + retrieval trace) was a library
that nothing called — implemented and green, but hollow in production.

Two endpoints:

* ``POST /api/context/resolve`` — resolve one address to tiered content plus the
  unified retrieval trace (017 FR-17). Supports a ``batch`` of addresses so a
  caller can hydrate several context slots in one round trip.
* ``GET /api/context/trace`` — read back a trace by id.

Visibility is **delegated**, never re-implemented: each address type is checked
by its owning backend (017 ``visible_to`` / 005-014-015 tenant isolation /
004-018 org scope / 002 participant set). Invisible addresses are reported
per-item rather than failing the whole batch, so one denied address cannot hide
the others.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.context_space.router import resolve_memory
from app.context_space.trace import TraceRecord
from app.context_space.visibility import (
    ContextNotFoundError,
    ContextVisibilityError,
)

router = APIRouter(prefix="/api/context", tags=["context"])


class ResolveRequest(BaseModel):
    """Resolve one or more ``mogo://`` addresses."""

    uri: str = Field(default="", description="Single mogo:// address (ignored when batch is set)")
    uris: list[str] = Field(default_factory=list, description="Batch of mogo:// addresses")
    tier: Optional[str] = Field(default=None, description="Force a tier: L0 / L1 / L2")
    session_id: str = Field(default="", description="Bind the trace to a session (FR-17)")
    turn_id: str = Field(default="", description="Bind the trace to a turn (FR-17)")


class ResolvedItem(BaseModel):
    """One resolution outcome (success or a typed failure)."""

    uri: str
    ok: bool
    resolved: Optional[dict[str, Any]] = None
    error: str = ""
    reason: str = ""


class ResolveResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict[str, Any]


# --- in-memory trace ring (observability channel, not the 001 audit stream) ---

_TRACE_RING_SIZE = 200
_TRACE_RING: dict[str, dict[str, Any]] = {}


def _remember_trace(trace: dict[str, Any]) -> None:
    """Store a trace for later readback, evicting the oldest when full."""
    trace_id = str(trace.get("trace_id") or "")
    if not trace_id:
        return
    _TRACE_RING[trace_id] = trace
    while len(_TRACE_RING) > _TRACE_RING_SIZE:
        oldest = next(iter(_TRACE_RING))
        _TRACE_RING.pop(oldest, None)


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_context(
    payload: ResolveRequest,
    authorization: str = Header(default=""),
) -> ResolveResponse:
    """Resolve ``mogo://`` addresses into tiered content + a unified trace.

    Delegates viewer resolution to the existing auth helper, then hands off to
    :func:`app.context_space.router.resolve_memory`, which routes to the owning
    tenant adapter and enforces backend-specific visibility.
    """
    from app.api.endpoints.auth import _resolve_session_user

    resolved_auth = await _resolve_session_user(authorization)
    tenant_id = str(resolved_auth.get("main_id") or "")
    viewer_id = str(resolved_auth.get("user_id") or "")
    viewer_role = str(resolved_auth.get("role") or "")
    is_workspace_member = bool(resolved_auth.get("is_workspace_member") or False)

    uris = [u for u in ([payload.uri] if payload.uri else []) + list(payload.uris or []) if u]
    if not uris:
        raise HTTPException(status_code=400, detail="uri or uris is required")
    if len(uris) > 50:
        raise HTTPException(status_code=400, detail="at most 50 uris per request")

    items: list[ResolvedItem] = []
    traces: list[dict[str, Any]] = []
    for uri in uris:
        try:
            out = await resolve_memory(
                uri,
                tenant_id=tenant_id,
                viewer_id=viewer_id,
                viewer_role=viewer_role,
                is_workspace_member=is_workspace_member,
                tier=payload.tier,
                session_id=payload.session_id,
                turn_id=payload.turn_id,
            )
        except ContextVisibilityError:
            # Report per-item: a denied address must not fail the whole batch.
            items.append(
                ResolvedItem(uri=uri, ok=False, error="visibility_denied", reason="visibility_denied")
            )
            continue
        except ContextNotFoundError:
            items.append(
                ResolvedItem(uri=uri, ok=False, error="not_found", reason="unresolved")
            )
            continue
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 — never leak internals
            log_print(f"[api.endpoints.context_space] silent exception caught: {exc}", flush=True)
            items.append(
                ResolvedItem(uri=uri, ok=False, error="internal_error", reason=type(exc).__name__)
            )
            continue

        trace = out.get("trace") or {}
        if trace:
            traces.append(trace)
            _remember_trace(trace)
        items.append(ResolvedItem(uri=uri, ok=True, resolved=out.get("resolved") or {}))

    return ResolveResponse(
        code=0,
        message="ok",
        data={
            "items": [item.model_dump() for item in items],
            "resolved_count": sum(1 for i in items if i.ok),
            "failed_count": sum(1 for i in items if not i.ok),
            "traces": traces,
        },
    )


@router.get("/trace/{trace_id}", response_model=ResolveResponse)
async def get_context_trace(
    trace_id: str,
    authorization: str = Header(default=""),
) -> ResolveResponse:
    """Read back a unified retrieval trace by id (017 FR-17 replay)."""
    from app.api.endpoints.auth import _resolve_session_user

    await _resolve_session_user(authorization)
    trace = _TRACE_RING.get(str(trace_id))
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return ResolveResponse(code=0, message="ok", data={"trace": trace})


__all__ = ["TraceRecord", "router"]
