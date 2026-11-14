"""Friction detection (011 FR-1 / clarify OQ-1).

Three friction signals:

1. ``failed_then_succeeded`` — a call failed and then succeeded after >= 1 retry
   (captured automatically);
2. ``human_correction`` — a human corrected or rejected the output (captured
   automatically);
3. ``explicit_mark`` — the user explicitly flagged "this went wrong" (**requires
   an explicit user action**, never inferred).

The first two are captured by default; the third only fires when the caller passes
an explicit mark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FrictionKind(str, Enum):
    FAILED_THEN_SUCCEEDED = "failed_then_succeeded"
    HUMAN_CORRECTION = "human_correction"
    EXPLICIT_MARK = "explicit_mark"


# Signals captured automatically (no user action needed).
AUTO_CAPTURED = frozenset({FrictionKind.FAILED_THEN_SUCCEEDED.value, FrictionKind.HUMAN_CORRECTION.value})


@dataclass
class FrictionSignal:
    """An observed friction event, ready to become an experience fragment."""

    kind: str
    scene: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    result: str = ""
    retries: int = 0
    feedback: str = ""
    source_session: str = ""
    tenant_id: str = "default"

    @property
    def captured_automatically(self) -> bool:
        return self.kind in AUTO_CAPTURED


def detect_friction(
    *,
    attempts: int = 0,
    succeeded: bool = False,
    corrected: bool = False,
    explicit_mark: bool = False,
    scene: Optional[list[str]] = None,
    actions: Optional[list[str]] = None,
    result: str = "",
    feedback: str = "",
    source_session: str = "",
    tenant_id: str = "default",
) -> Optional[FrictionSignal]:
    """Classify a call outcome into a friction signal (or ``None``).

    Priority: an explicit mark wins; then human correction; then a failure that was
    eventually solved after at least one retry.
    """
    retries = max(0, int(attempts) - 1) if succeeded else 0

    if explicit_mark:
        return FrictionSignal(
            kind=FrictionKind.EXPLICIT_MARK.value,
            scene=list(scene or []),
            actions=list(actions or []),
            result=result,
            retries=retries,
            feedback=feedback,
            source_session=source_session,
            tenant_id=tenant_id,
        )

    if corrected:
        return FrictionSignal(
            kind=FrictionKind.HUMAN_CORRECTION.value,
            scene=list(scene or []),
            actions=list(actions or []),
            result=result,
            retries=retries,
            feedback=feedback,
            source_session=source_session,
            tenant_id=tenant_id,
        )

    if succeeded and retries >= 1:
        return FrictionSignal(
            kind=FrictionKind.FAILED_THEN_SUCCEEDED.value,
            scene=list(scene or []),
            actions=list(actions or []),
            result=result or "failed then succeeded",
            retries=retries,
            feedback=feedback,
            source_session=source_session,
            tenant_id=tenant_id,
        )

    return None


def detect_friction_batch(events: list[dict[str, Any]]) -> list[FrictionSignal]:
    """Run ``detect_friction`` over a batch of raw event dicts."""
    signals: list[FrictionSignal] = []
    for event in events:
        signal = detect_friction(**event)
        if signal is not None:
            signals.append(signal)
    return signals
