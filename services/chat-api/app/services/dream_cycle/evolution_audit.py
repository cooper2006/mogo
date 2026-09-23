"""Self-evolution audit + configurable thresholds (011 T017-T018).

T017: every self-evolution event (capture / generate / MR / deprecation /
restore) is recorded through the 001 audit sink so the full chain is
auditable.

T018: thresholds and scan period are configurable (single place —
``EvolutionConfig``) rather than scattered magic numbers.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

# 001 audit sink signature (kept generic so the same sink serves all events).
AuditSink = Callable[..., Any]

AUDIT_EVENT_TYPES = ("capture", "generate", "mr", "deprecate", "restore")


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class EvolutionConfig:
    """011 T018 — configurable scan period + confidence / deprecation thresholds."""
    scan_interval_hours: int = 24
    jaccard_threshold: float = 0.7
    min_samples: int = 5
    low_adoption_window_days: int = 14
    low_adoption_min_exposure: int = 20
    low_adoption_rate: float = 0.10
    shadow_ratio: float = 0.1

    def confidence_gate(self, jaccard: float, samples: int) -> bool:
        return jaccard >= self.jaccard_threshold and samples >= self.min_samples

    def is_low_adoption(self, exposure: int, adopted: int, window_days: int) -> bool:
        if exposure <= 0:
            return False
        rate = adopted / exposure
        return (
            exposure >= self.low_adoption_min_exposure
            and window_days <= self.low_adoption_window_days
            and rate < self.low_adoption_rate
        )


def record_evolution_event(
    audit_sink: AuditSink,
    *,
    event_type: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    ts: datetime.datetime | None = None,
) -> dict[str, Any]:
    """011 T017 — record one self-evolution event into the 001 audit sink."""
    if event_type not in AUDIT_EVENT_TYPES:
        raise ValueError(f"unknown self-evolution audit event type: {event_type!r}")
    document = {
        "event_type": event_type,
        "actor": actor,
        "ts": ts or _utcnow(),
        "payload": dict(payload or {}),
    }
    result = audit_sink(
        event_type=event_type,
        actor=actor,
        ts=document["ts"],
        payload=document["payload"],
    )
    return result if isinstance(result, dict) else document


def audit_capture(fragment: dict[str, Any], *, sink: AuditSink, actor: str) -> dict[str, Any]:
    return record_evolution_event(sink, event_type="capture", actor=actor, payload=fragment)


def audit_generate(candidates: int, *, sink: AuditSink, actor: str) -> dict[str, Any]:
    return record_evolution_event(sink, event_type="generate", actor=actor, payload={"candidates": candidates})


def audit_mr(mr_document: dict[str, Any], *, sink: AuditSink, actor: str) -> dict[str, Any]:
    return record_evolution_event(sink, event_type="mr", actor=actor, payload=mr_document)


def audit_deprecate(record: dict[str, Any], *, sink: AuditSink, actor: str) -> dict[str, Any]:
    return record_evolution_event(sink, event_type="deprecate", actor=actor, payload=record)


def audit_restore(record: dict[str, Any], *, sink: AuditSink, actor: str) -> dict[str, Any]:
    return record_evolution_event(sink, event_type="restore", actor=actor, payload=record)


__all__ = [
    "AUDIT_EVENT_TYPES",
    "AuditSink",
    "EvolutionConfig",
    "audit_capture",
    "audit_deprecate",
    "audit_generate",
    "audit_mr",
    "audit_restore",
    "record_evolution_event",
]
