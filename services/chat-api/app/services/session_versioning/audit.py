"""Session event audit hook (002 T021 / FR-9).

Every session event (enter / leave / commit / resume / share / dereference) is
recorded into the 001 gatekeeper audit sink (`gate_events`) with the fields
the 002 audit contract requires: actor, timestamp, session id, event type, and
the referenced object (snapshot / share / version id).

The hook is a thin recorder: it normalises the event into the audit schema and
delegates persistence to the 001 audit layer, so session events share the same
audit trail, retention, and compliance reporting as governance events.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

AUDIT_EVENT_TYPES = frozenset({"enter", "leave", "commit", "resume", "share", "dereference"})

# Audit fields required by the 002 T021 contract.
SESSION_AUDIT_FIELDS = ("actor", "ts", "session_id", "event_type", "target_ref")


def record_session_event(
    audit_sink: Callable[..., Any],
    session_id: str,
    *,
    event_type: str,
    actor: str,
    target_ref: str = "",
    ts: datetime.datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalise a session event and write it through the 001 audit sink.

    ``audit_sink`` is the 001 gatekeeper audit writer (a callable that accepts
    ``event_type`` / ``actor`` / ``ts`` / ``session_id`` / ``target_ref`` /
    ``extra``). The returned dict is the audit document (useful for tests and
    in-memory sinks).
    """
    if event_type not in AUDIT_EVENT_TYPES:
        raise ValueError(f"unknown session audit event type: {event_type!r}")
    document = {
        "event_type": event_type,
        "actor": actor,
        "ts": ts or datetime.datetime.now(datetime.timezone.utc),
        "session_id": session_id,
        "target_ref": target_ref,
        "extra": dict(extra or {}),
    }
    result = audit_sink(
        event_type=event_type,
        actor=actor,
        ts=document["ts"],
        session_id=session_id,
        target_ref=target_ref,
        extra=document["extra"],
    )
    # The returned document is the audit record; merge the sink result if it
    # returns its own document, otherwise return the normalised document.
    if isinstance(result, dict) and result:
        return result
    return document


def validate_audit_document(document: dict[str, Any]) -> None:
    """Raise if a session audit document is missing a required T021 field."""
    for field_name in SESSION_AUDIT_FIELDS:
        if field_name not in document:
            raise KeyError(f"session audit document missing required field: {field_name}")
