"""Three-scope memory (feature 017) — D4 target state.

Memory lives at one of three scopes — **personal / project / department** —
with visibility isolated per scope, default scope chosen by session context,
promotion to department requiring authorization, and a configurable decay
lifecycle. There is no runtime ``workspace`` / ``org`` alias (D4).

This package holds the dependency-light core (scope model / visibility /
lifecycle / server-built viewer context), so it is unit-testable without a
database.
"""

from __future__ import annotations

from .scope import (
    DEFAULT_PROJECT_ID,
    DEPARTMENT_PROMOTION_ROLES,
    SCOPE_VISIBILITY,
    Memory,
    MemoryAccessError,
    MemoryScope,
    Visibility,
    can_promote_to_department,
    promote_to_department,
    resolve_default_scope,
    visible_to,
)
from .viewer import (
    MemoryViewerContext,
    build_viewer_context,
    resolve_viewer_context,
    resolve_viewer_from_identity,
)
from .lifecycle import (
    DEFAULT_DECAY_DAYS,
    MemoryLifecycle,
    is_expired,
    seconds_until_expiry,
)
from .tiering import NoopSummarizer, Summarizer, TierResult, tier_content
from .address import VALID_SCOPES, MemoryAddress, parse_memory_uri
from .sediment import (
    NoopSessionSummarizer,
    SessionSummarizer,
    build_session_memory,
    on_session_end,
)

__all__ = [
    # scope / visibility
    "MemoryScope",
    "Visibility",
    "SCOPE_VISIBILITY",
    "DEFAULT_PROJECT_ID",
    "DEPARTMENT_PROMOTION_ROLES",
    "Memory",
    "MemoryAccessError",
    "resolve_default_scope",
    "visible_to",
    "can_promote_to_department",
    "promote_to_department",
    # viewer context
    "MemoryViewerContext",
    "build_viewer_context",
    "resolve_viewer_context",
    "resolve_viewer_from_identity",
    # lifecycle
    "MemoryLifecycle",
    "is_expired",
    "seconds_until_expiry",
    "DEFAULT_DECAY_DAYS",
    # tiering
    "NoopSummarizer",
    "Summarizer",
    "TierResult",
    "tier_content",
    # address
    "MemoryAddress",
    "parse_memory_uri",
    "VALID_SCOPES",
    # sediment
    "NoopSessionSummarizer",
    "SessionSummarizer",
    "build_session_memory",
    "on_session_end",
]
