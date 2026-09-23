"""Memory lifecycle: decay / cleanup (017 FR-8 / clarify OQ-2).

Decay period defaults to **30 days**; accessing a memory resets its timer. Once a
memory has been idle past the decay window it is eligible for cleanup (archival or
deletion, configurable).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_DECAY_DAYS = 30
SECONDS_PER_DAY = 86400

# Cleanup disposition once decayed (configurable).
CLEANUP_ARCHIVE = "archive"
CLEANUP_DELETE = "delete"


@dataclass
class MemoryLifecycle:
    """Configurable decay / cleanup policy."""

    decay_days: int = DEFAULT_DECAY_DAYS
    cleanup: str = CLEANUP_ARCHIVE

    @property
    def decay_seconds(self) -> float:
        return float(max(1, int(self.decay_days)) * SECONDS_PER_DAY)


def is_expired(
    *,
    last_accessed_at: float,
    now: float,
    lifecycle: MemoryLifecycle | None = None,
) -> bool:
    """Whether a memory has been idle past its decay window (FR-8)."""
    policy = lifecycle or MemoryLifecycle()
    return (now - float(last_accessed_at)) >= policy.decay_seconds


def seconds_until_expiry(
    *,
    last_accessed_at: float,
    now: float,
    lifecycle: MemoryLifecycle | None = None,
) -> float:
    """Seconds remaining before decay (negative once already expired)."""
    policy = lifecycle or MemoryLifecycle()
    return policy.decay_seconds - (now - float(last_accessed_at))


def touch(last_accessed_at: float, now: float) -> float:
    """Accessing a memory resets its decay timer (clarify OQ-2)."""
    return float(now)
