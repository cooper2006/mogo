"""Unified retrieval trace (017 FR-17 / 021).

Every resolved address produces a :class:`TraceRecord` capturing *what* was
returned, *which tier* was used, *why* it was selected, and *what* was skipped
(and why). Traces are bound to ``session_id`` / ``turn_id`` so a conversation can
replay *why this memory was recalled*. They land in the observability channel
(not the 001 audit stream) to avoid polluting the security audit log; high-value
hits can be sampled into 001 by the caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass
class TraceRecord:
    """One unified retrieval trace (FR-17)."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    turn_id: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "candidates": self.candidates,
            "skipped": self.skipped,
        }


def build_trace(
    candidates: Iterable[dict[str, Any]],
    skipped: Iterable[dict[str, Any]],
    *,
    session_id: str = "",
    turn_id: str = "",
) -> TraceRecord:
    """Build a trace from candidate / skipped entries (FR-17)."""
    return TraceRecord(
        session_id=session_id,
        turn_id=turn_id,
        candidates=[dict(c) for c in candidates],
        skipped=[dict(s) for s in skipped],
    )


def candidate_entry(
    *,
    uri: str,
    tier_used: str,
    hit_reason: str,
    score: float = 0.0,
) -> dict[str, Any]:
    """Construct a candidate trace entry."""
    return {
        "uri": uri,
        "tier_used": tier_used,
        "hit_reason": hit_reason,
        "score": float(score),
    }


def skipped_entry(*, uri: str, reason: str) -> dict[str, Any]:
    """Construct a skipped trace entry."""
    return {"uri": uri, "reason": reason}


__all__ = ["TraceRecord", "build_trace", "candidate_entry", "skipped_entry"]
