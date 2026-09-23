"""Resilience event records (007 T003).

Events are attached to the existing ``token_usage_logs`` records as *extra
fields* — no new collection (clarify OQ-4):

* ``failover_from`` / ``failover_to`` — provider switch on the same call;
* ``degradation_step`` — index in the degradation chain that served the call;
* ``degradation_reason`` — enumerated reason (429 / 5xx / timeout / manual).

The structure is intentionally plain so it can be merged into whatever document
the metering layer (``token_usage``) already produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DegradationReason(str, Enum):
    """Enumerated degradation causes (007 FR-11) — never free text."""

    UPSTREAM_429 = "429"
    UPSTREAM_5XX = "5xx"
    TIMEOUT = "timeout"
    MANUAL = "manual"


def reason_from_status(status_code: Optional[int]) -> DegradationReason:
    if status_code == 429:
        return DegradationReason.UPSTREAM_429
    if status_code is not None and 500 <= status_code < 600:
        return DegradationReason.UPSTREAM_5XX
    if status_code in (408, 504):
        return DegradationReason.TIMEOUT
    return DegradationReason.MANUAL


@dataclass
class ResilienceEvent:
    """A single resilience event to be merged into the usage log."""

    event: str                       # failover | degradation | retry
    provider_from: str = ""
    provider_to: str = ""
    reason: str = ""
    attempt: int = 0                 # 1-based attempt number
    extra: dict[str, Any] = field(default_factory=dict)

    def as_log_fields(self) -> dict[str, Any]:
        """Flatten into the extra fields attached to ``token_usage_logs``."""
        fields: dict[str, Any] = {"resilience_event": self.event}
        if self.provider_from or self.provider_to:
            fields["failover_from"] = self.provider_from
            fields["failover_to"] = self.provider_to
        if self.reason:
            fields["degradation_reason"] = self.reason
        if self.attempt:
            fields["attempt"] = self.attempt
        fields.update(self.extra)
        return fields


def failover_fields(provider_from: str, provider_to: str, *, attempt: int = 1) -> dict[str, Any]:
    return ResilienceEvent(
        event="failover",
        provider_from=provider_from,
        provider_to=provider_to,
        attempt=attempt,
    ).as_log_fields()


def degradation_fields(step: int, *, provider: str = "", reason: str = "") -> dict[str, Any]:
    return ResilienceEvent(
        event="degradation",
        provider_to=provider,
        reason=reason,
        extra={"degradation_step": step},
    ).as_log_fields()
