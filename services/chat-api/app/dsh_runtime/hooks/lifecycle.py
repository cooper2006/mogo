"""Other session / lifecycle hook events (009 T013-T014 / US3).

Implements the remaining four hook events — ``SessionStart``, ``PostToolUse``,
``SessionEnd``, ``MemoryCommit`` — with correct payloads (FR-12). They bridge
to the 002 session events and can carry structured data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import (
    MEMORY_COMMIT,
    POST_TOOL_USE,
    SESSION_END,
    SESSION_START,
    HookRegistry,
)


@dataclass
class HookEventPayload:
    """A hook event with its structured payload (009 FR-12)."""
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = ""

    def as_document(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "actor": self.actor,
            **self.payload,
        }


def emit_session_start(
    registry: HookRegistry,
    *,
    session_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> HookEventPayload | None:
    """Emit ``SessionStart`` (bridges to 002 session enter). Returns None when disabled."""
    if not registry.is_enabled(SESSION_START):
        return None
    return HookEventPayload(
        event=SESSION_START,
        actor=actor,
        payload={"session_id": session_id, **(payload or {})},
    )


def emit_post_tool_use(
    registry: HookRegistry,
    *,
    tool: str,
    result: Any,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> HookEventPayload | None:
    """Emit ``PostToolUse`` (bridges to 002 tool call completion)."""
    if not registry.is_enabled(POST_TOOL_USE):
        return None
    return HookEventPayload(
        event=POST_TOOL_USE,
        actor=actor,
        payload={"tool": tool, "result": result, **(payload or {})},
    )


def emit_session_end(
    registry: HookRegistry,
    *,
    session_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> HookEventPayload | None:
    """Emit ``SessionEnd`` (bridges to 002 session leave)."""
    if not registry.is_enabled(SESSION_END):
        return None
    return HookEventPayload(
        event=SESSION_END,
        actor=actor,
        payload={"session_id": session_id, **(payload or {})},
    )


def emit_memory_commit(
    registry: HookRegistry,
    *,
    session_id: str,
    memory_ref: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> HookEventPayload | None:
    """Emit ``MemoryCommit`` (bridges to 002 commit)."""
    if not registry.is_enabled(MEMORY_COMMIT):
        return None
    return HookEventPayload(
        event=MEMORY_COMMIT,
        actor=actor,
        payload={"session_id": session_id, "memory_ref": memory_ref, **(payload or {})},
    )


def all_lifecycle_events(registry: HookRegistry) -> list[str]:
    """The enabled lifecycle events (SessionStart/SessionEnd/MemoryCommit)."""
    return [event for event in registry.lifecycle_events() if registry.is_enabled(event)]


__all__ = [
    "HookEventPayload",
    "all_lifecycle_events",
    "emit_memory_commit",
    "emit_post_tool_use",
    "emit_session_end",
    "emit_session_start",
]
