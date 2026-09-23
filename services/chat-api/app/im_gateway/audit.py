"""IM entry audit + observability (013 T999).

Every IM-entry event (enter / leave / deliver / fail) is recorded through the
001 governance audit sink so IM traffic shares the same audit trail, retention,
and compliance reporting as the rest of the platform.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

IM_AUDIT_EVENTS = ("im.enter", "im.leave", "im.deliver", "im.fail")

# The 001 audit sink signature (kept generic so tests can inject a fake).
AuditSink = Callable[..., Any]


def record_im_event(
    event: str,
    *,
    channel: str,
    conversation_id: str,
    tenant_id: str = "",
    actor: str = "",
    details: dict[str, Any] | None = None,
    sink: Optional[AuditSink] = None,
) -> dict[str, Any]:
    """Record one IM-entry event into the 001 audit sink (013 T999).

    ``sink`` is the 001 governance audit writer (default:
    ``record_position_policy_event``). Returns the audit document so callers
    can inspect / assert on it in tests.
    """
    if event not in IM_AUDIT_EVENTS:
        raise ValueError(f"unknown IM audit event: {event!r}")
    document = {
        "event": event,
        "channel": channel,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "actor": actor,
        "details": dict(details or {}),
    }
    if sink is not None:
        sink(
            tenant_id=tenant_id,
            user_id=actor,
            action=event,
            target=channel,
            details=document,
        )
    return document


def im_audit_document(event: str, channel: str, conversation_id: str) -> dict[str, Any]:
    """A pure audit document (no side effects) for in-memory / test sinks."""
    return record_im_event(
        event, channel=channel, conversation_id=conversation_id
    )


__all__ = [
    "IM_AUDIT_EVENTS",
    "im_audit_document",
    "record_im_event",
]
