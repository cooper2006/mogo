"""Business source specs + PII masking (014 FR-1 / FR-2 / FR-10 / FR-11).

Sources are pulled on a schedule (no CDC, clarify OQ-3); the first delivery targets
CRM over a **read-only** replica. PII fields are masked before indexing so retrieved
results never carry plaintext (FR-10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .entities import PII_FIELDS

DEFAULT_PULL_INTERVAL = "daily"
SUPPORTED_INTERVALS = ("once", "daily", "weekly")


class SourceStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    SYNCING = "syncing"


@dataclass
class SourceSpec:
    """Declarative spec for one business source (CRM first)."""

    name: str
    kind: str = "crm"
    read_only: bool = True
    interval: str = DEFAULT_PULL_INTERVAL
    entity_types: list[str] = field(default_factory=list)
    connection_ref: str = ""     # pointer to credentials (never inline, FR-8)

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("source name must not be empty")
        if self.interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"unsupported pull interval: {self.interval!r}")
        if not self.read_only:
            # MOVO never writes back to a business system (Non-Goal).
            raise ValueError("business sources must be read-only")


def is_source_unavailable(status: str) -> bool:
    """Whether a source is unavailable, so results must be labelled stale (FR-11)."""
    return str(status) == SourceStatus.UNAVAILABLE.value


def mask_pii_fields(fields: dict[str, Any], *, strategy: str = "mask") -> dict[str, Any]:
    """Mask PII fields before indexing (FR-10).

    ``mask``     -> replace with a fixed token;
    ``hash``     -> deterministic short digest;
    ``remove``   -> drop the field entirely.
    """
    masked: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in PII_FIELDS:
            masked[key] = value
            continue
        if strategy == "remove":
            continue
        if strategy == "hash":
            import hashlib

            masked[key] = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
        else:
            masked[key] = "***"
    return masked


def build_unavailable_notice(system: str) -> dict[str, str]:
    """The notice returned when a source is down (never a stale-data masquerade)."""
    return {
        "status": SourceStatus.UNAVAILABLE.value,
        "sourceSystem": system,
        "message": f"数据源不可用：{system}",
    }
