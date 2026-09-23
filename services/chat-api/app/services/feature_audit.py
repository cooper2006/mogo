"""Audit/observability hooks (T999) for 014/015/016/017/018 features.

Each feature's key events are funneled into a single 001-style audit sink so
they share the same trail, retention, and compliance reporting. The helpers
below are thin recorders: they normalise the event into a document and write
it through the injected sink (tests use an in-memory sink; production uses
the 001 governance audit writer).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# The generic audit sink: ``sink(event, document)``.
AuditSink = Callable[[str, dict[str, Any]], Any]

FEATURE_AUDIT_EVENTS: dict[str, tuple[str, ...]] = {
    "014": ("entity.indexed", "entity.searched"),
    "015": ("kg.mutated", "kg.conflict.resolved", "kg.audited"),
    "016": ("skill.quality.marked", "skill.quality.restored"),
    "017": ("memory.promoted", "memory.decayed", "memory.restored"),
    "018": ("asset.registered", "asset.status.changed", "asset.a2a.marked"),
}


def record_feature_event(
    feature: str,
    event: str,
    document: dict[str, Any],
    *,
    sink: Optional[AuditSink] = None,
) -> dict[str, Any]:
    """Normalise one feature event and write it through the audit sink (T999).

    ``feature`` must be a known feature code (014/015/016/017/018); an unknown
    code raises so a mis-labelled event is not silently lost.
    """
    known = FEATURE_AUDIT_EVENTS.get(feature)
    if known is None:
        raise ValueError(f"unknown feature: {feature!r}")
    if event not in known:
        raise ValueError(f"unknown audit event for {feature}: {event!r}")
    record = {"feature": feature, "event": event, **document}
    if sink is not None:
        sink(event, record)
    return record


def audit_document(event: str, feature: str, **fields: Any) -> dict[str, Any]:
    """A pure audit document (no side effects) for in-memory / test sinks."""
    return record_feature_event(feature, event, fields)


__all__ = [
    "FEATURE_AUDIT_EVENTS",
    "audit_document",
    "record_feature_event",
]
