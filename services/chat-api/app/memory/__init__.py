"""Three-scope memory (feature 017).

Memory lives at one of three scopes — **personal / workspace / org** — with
visibility isolated per scope, default scope chosen by session type, promotion to
org requiring authorization, and a configurable decay lifecycle.

This package holds the dependency-light core (scope model / visibility / lifecycle),
so it is unit-testable without a database.
"""

from __future__ import annotations

from .scope import MemoryScope, Memory, Visibility, resolve_default_scope, visible_to
from .lifecycle import (
    DEFAULT_DECAY_DAYS,
    MemoryLifecycle,
    is_expired,
    seconds_until_expiry,
)

__all__ = [
    "MemoryScope",
    "Memory",
    "Visibility",
    "resolve_default_scope",
    "visible_to",
    "MemoryLifecycle",
    "is_expired",
    "seconds_until_expiry",
    "DEFAULT_DECAY_DAYS",
]
