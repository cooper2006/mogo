"""Friction capture (011 T005-T006 / US1).

Extracts experience fragments from session / tool-call signals. Three friction
categories are captured:

- ``retry``       – a tool call that had to be retried (transient failure).
- ``fallback``    – a tool call that fell back to a degraded path.
- ``timeout``     – a tool call that hit a timeout.

Each fragment records the context needed to later generate an improvement
candidate (tool, stage, prompt preview, outcome) while keeping it compact and
storing only pointers / previews — never large payloads or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

FRICION_CATEGORIES = ("retry", "fallback", "timeout")
# Max characters kept in a prompt preview on a fragment (011 OQ: keep compact).
PROMPT_PREVIEW_LIMIT = 120


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FrictionFragment:
    """One captured friction experience fragment."""
    key: str
    category: str
    tool: str
    stage: str = ""
    prompt_preview: str = ""
    outcome: str = ""
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.category not in FRICION_CATEGORIES:
            raise ValueError(f"unknown friction category: {self.category!r}")
        if not str(self.key or "").strip():
            raise ValueError("friction fragment key must not be empty")

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "tool": self.tool,
            "stage": self.stage,
            "prompt_preview": self.prompt_preview[:PROMPT_PREVIEW_LIMIT],
            "outcome": self.outcome,
            "created_at": self.created_at,
        }


def extract_friction_from_signals(
    signals: Iterable[dict[str, Any]],
    *,
    store: Any = None,
) -> list[FrictionFragment]:
    """Extract friction fragments from call/tool signals (T005).

    A signal carries ``{key, tool, stage, retries, fell_back, timed_out,
    prompt, outcome}``. Each matching signal yields one fragment. When a
    ``store`` is provided, each fragment is persisted to the experience store
    (US1 落经验存储).
    """
    fragments: list[FrictionFragment] = []
    for item in signals:
        key = str(item.get("key") or "").strip()
        tool = str(item.get("tool") or "")
        if not key or not tool:
            continue
        prompt = str(item.get("prompt") or "")
        outcome = str(item.get("outcome") or "")
        retries = int(item.get("retries") or 0)
        fell_back = bool(item.get("fell_back"))
        timed_out = bool(item.get("timed_out"))
        if retries > 0 and fell_back:
            category, out = "fallback", outcome or "degraded path used"
        elif retries > 0:
            category, out = "retry", outcome or f"retried {retries}x"
        elif timed_out:
            category, out = "timeout", outcome or "timed out"
        else:
            continue
        fragment = FrictionFragment(
            key=key,
            category=category,
            tool=tool,
            stage=str(item.get("stage") or ""),
            prompt_preview=prompt,
            outcome=out,
        )
        fragments.append(fragment)
        if store is not None:
            store.save(fragment.as_document())
    return fragments


class FrictionStore:
    """In-memory experience store; the Mongo-backed implementation plugs in here."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def save(self, document: dict[str, Any]) -> None:
        self.rows.append(document)

    def recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.rows[-limit:]
