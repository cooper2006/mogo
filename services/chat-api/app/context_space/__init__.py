"""Unified context address space (feature 021).

A thin *virtual routing + adapter + delegated visibility + unified trace* layer.
It does **not** own storage — each backend (memory / resource / skill / session)
keeps its own store; this layer only orchestrates addressing, tier selection,
visibility delegation, and retrieval traceability.

All four roots are wired: ``memory`` (017), ``resource`` (005/014/015),
``skill`` (004/018), ``session`` (002).
"""

from __future__ import annotations

from .address import parse_context_uri
from .adapters.memory import MemoryTierAdapter
from .adapters.resource import ResourceTierAdapter
from .adapters.session import SessionTierAdapter
from .adapters.skill import SkillTierAdapter
from .router import ContextVisibilityError, resolve_memory
from .trace import build_trace, TraceRecord
from .visibility import ViewerContext

__all__ = [
    "ContextVisibilityError",
    "MemoryTierAdapter",
    "ResourceTierAdapter",
    "SessionTierAdapter",
    "SkillTierAdapter",
    "TraceRecord",
    "ViewerContext",
    "build_trace",
    "parse_context_uri",
    "resolve_memory",
]
