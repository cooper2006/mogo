"""Hook event dispatch (009 FR-1 / FR-12 — closes the emit → consume loop).

``lifecycle.emit_*`` only *builds* a :class:`HookEventPayload`; before this module
the payload had no consumer, so emitting was a no-op (the 017 sedimentation path
papered over that with a throwaway ``HookRegistry``). This dispatcher is the
missing half: a process-local subscriber registry plus async-aware ``dispatch``.

Design constraints:

* **No new infrastructure.** 009 is a hook *mechanism*; the bus is an in-process
  registry, not Kafka/Redis. That keeps the seam testable and avoids inventing
  infrastructure the spec never asked for.
* **Isolated failures.** A failing subscriber must never break the emitting
  request — hook observers are advisory. Failures are collected and returned so
  the caller can log them.
* **Async-aware.** Subscribers may be sync or async; both are supported so
  simple consumers do not need to be coroutines.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Optional, Union

from .lifecycle import (
    HookEventPayload,
    emit_memory_commit,
    emit_post_tool_use,
    emit_session_end,
    emit_session_start,
)
from .registry import (
    HOOK_EVENTS,
    MEMORY_COMMIT,
    POST_TOOL_USE,
    SESSION_END,
    SESSION_START,
    HookRegistry,
)

Subscriber = Callable[[HookEventPayload], Union[None, Awaitable[None]]]

# event -> ordered subscribers. Dict preserves insertion order so emission is
# deterministic (important for replay/debugging).
_SUBSCRIBERS: dict[str, list[Subscriber]] = {}


def subscribe(event: str, handler: Subscriber) -> Subscriber:
    """Register ``handler`` for ``event``. Returns it (usable as a decorator).

    Raises ``ValueError`` for an unknown event name so typos fail loudly instead
    of silently never firing.
    """
    if event not in HOOK_EVENTS:
        raise ValueError(f"unknown hook event: {event!r}")
    _SUBSCRIBERS.setdefault(event, []).append(handler)
    return handler


def unsubscribe(event: str, handler: Subscriber) -> bool:
    """Remove a previously registered handler. Returns True when one was removed."""
    handlers = _SUBSCRIBERS.get(event)
    if not handlers or handler not in handlers:
        return False
    handlers.remove(handler)
    return True


def clear_subscribers(event: Optional[str] = None) -> None:
    """Drop subscribers for one event, or all of them. Mainly for test isolation."""
    if event is None:
        _SUBSCRIBERS.clear()
    else:
        _SUBSCRIBERS.pop(event, None)


def subscriber_count(event: Optional[str] = None) -> int:
    """How many subscribers are registered (for one event, or in total)."""
    if event is None:
        return sum(len(v) for v in _SUBSCRIBERS.values())
    return len(_SUBSCRIBERS.get(event, []))


async def dispatch(payload: Optional[HookEventPayload]) -> list[str]:
    """Deliver ``payload`` to its subscribers; return the names that failed.

    ``None`` payload (event disabled) is a no-op. A subscriber raising is
    isolated: the remaining subscribers still run.
    """
    if payload is None:
        return []
    failures: list[str] = []
    for handler in list(_SUBSCRIBERS.get(payload.event, [])):
        try:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 — observers must not break callers
            failures.append(f"{getattr(handler, '__qualname__', handler)}: {exc}")
    return failures


async def dispatch_session_end(
    session_id: str,
    *,
    actor: str = "",
    registry: Optional[HookRegistry] = None,
    payload: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Build **and** deliver a ``SessionEnd`` event (the full emit→consume loop).

    This is the entry point 002 calls when a session ends. The 017 sedimentation
    subscriber is registered by :mod:`app.memory.sediment`, so emitting here
    actually runs the memory write.
    """
    event = emit_session_end(
        registry or HookRegistry(enabled={SESSION_END}),
        session_id=session_id,
        actor=actor,
        payload=payload,
    )
    return await dispatch(event)


async def dispatch_session_start(
    session_id: str,
    *,
    actor: str = "",
    registry: Optional[HookRegistry] = None,
    payload: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Build and deliver a ``SessionStart`` event."""
    event = emit_session_start(
        registry or HookRegistry(enabled={SESSION_START}),
        session_id=session_id,
        actor=actor,
        payload=payload,
    )
    return await dispatch(event)


async def dispatch_post_tool_use(
    tool: str,
    *,
    result: Any = None,
    actor: str = "",
    registry: Optional[HookRegistry] = None,
    payload: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Build and deliver a ``PostToolUse`` event."""
    event = emit_post_tool_use(
        registry or HookRegistry(enabled={POST_TOOL_USE}),
        tool=tool,
        result=result,
        actor=actor,
        payload=payload,
    )
    return await dispatch(event)


async def dispatch_memory_commit(
    session_id: str,
    *,
    memory_ref: str,
    actor: str = "",
    registry: Optional[HookRegistry] = None,
    payload: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Build and deliver a ``MemoryCommit`` event."""
    event = emit_memory_commit(
        registry or HookRegistry(enabled={MEMORY_COMMIT}),
        session_id=session_id,
        memory_ref=memory_ref,
        actor=actor,
        payload=payload,
    )
    return await dispatch(event)


# Keep the module importable for sync contexts that only need the helpers above.
__all__ = [
    "Subscriber",
    "clear_subscribers",
    "dispatch",
    "dispatch_memory_commit",
    "dispatch_post_tool_use",
    "dispatch_session_end",
    "dispatch_session_start",
    "subscriber_count",
    "subscribe",
    "unsubscribe",
]
