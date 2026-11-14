"""Five-event hook registry (009 FR-1 / T003).

Registers the five hook events and tracks which are enabled. The first delivery
enables **PreToolUse only** (clarify OQ-3); the other four are registered as the
target state so wiring them later is a config change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# The five hook events.
SESSION_START = "SessionStart"
PRE_TOOL_USE = "PreToolUse"
POST_TOOL_USE = "PostToolUse"
SESSION_END = "SessionEnd"
MEMORY_COMMIT = "MemoryCommit"

HOOK_EVENTS: tuple[str, ...] = (
    SESSION_START,
    PRE_TOOL_USE,
    POST_TOOL_USE,
    SESSION_END,
    MEMORY_COMMIT,
)

# First-delivery enabled events (clarify OQ-3).
FIRST_DELIVERY_EVENTS: tuple[str, ...] = (PRE_TOOL_USE,)

# Session lifecycle events that bridge to 002.
SESSION_LIFECYCLE_EVENTS: tuple[str, ...] = (SESSION_START, SESSION_END, MEMORY_COMMIT)


class HookEvent(str, Enum):
    SESSION_START = SESSION_START
    PRE_TOOL_USE = PRE_TOOL_USE
    POST_TOOL_USE = POST_TOOL_USE
    SESSION_END = SESSION_END
    MEMORY_COMMIT = MEMORY_COMMIT


class RegistryError(ValueError):
    """Raised for an unknown hook event."""


@dataclass
class HookRegistry:
    """Tracks which hook events are enabled."""

    enabled: set[str] = field(default_factory=lambda: set(FIRST_DELIVERY_EVENTS))

    def __post_init__(self) -> None:
        for event in self.enabled:
            if event not in HOOK_EVENTS:
                raise RegistryError(f"unknown hook event: {event!r}")

    def is_enabled(self, event: str) -> bool:
        return event in self.enabled

    def enable(self, event: str) -> None:
        if event not in HOOK_EVENTS:
            raise RegistryError(f"unknown hook event: {event!r}")
        self.enabled.add(event)

    def disable(self, event: str) -> None:
        if event == PRE_TOOL_USE:
            # PreToolUse is the compliance interception point; keep it on.
            raise RegistryError("PreToolUse cannot be disabled")
        self.enabled.discard(event)

    def enabled_events(self) -> list[str]:
        """Enabled events in canonical order."""
        return [event for event in HOOK_EVENTS if event in self.enabled]

    def all_registered(self) -> list[str]:
        return list(HOOK_EVENTS)

    def lifecycle_events(self) -> list[str]:
        return list(SESSION_LIFECYCLE_EVENTS)
