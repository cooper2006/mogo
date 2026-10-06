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
from .tiering import NoopSummarizer, Summarizer, TierResult, tier_content
from .address import MemoryAddress, parse_memory_uri
from .sediment import NoopSessionSummarizer, SessionSummarizer, build_session_memory, on_session_end

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
    "NoopSummarizer",
    "Summarizer",
    "TierResult",
    "tier_content",
    "MemoryAddress",
    "parse_memory_uri",
    "NoopSessionSummarizer",
    "SessionSummarizer",
    "build_session_memory",
    "on_session_end",
]
