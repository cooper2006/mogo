"""Memory density tiering (017 FR-13 / FR-14 / FR-15).

Three tiers capture information density so retrieval can load *just enough*:

* **L0** — one-line summary (relevance pre-filter, exclude irrelevant fast)
* **L1** — overview / key points (decides which memory to drill into)
* **L2** — raw detail (the original ``content``, fetched only on demand)

Two generation paths (FR-15 "两者结合"):

* **write-time** — the caller supplies ``l0_summary`` / ``l1_overview``
  (produced upstream by an LLM / handler). Cost is paid up-front; first read is
  instant.
* **lazy fallback** — when a summary is missing or stale
  (``summary_refresh_days`` elapsed), a :class:`Summarizer` is invoked on demand.

This module is dependency-light (no DB / config imports) so it stays
unit-testable in isolation, mirroring ``scope.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

SUMMARY_REFRESH_DAYS_DEFAULT = 30
SECONDS_PER_DAY = 86_400


class Summarizer(Protocol):
    """Produces ``(l0_summary, l1_overview)`` for a raw content string."""

    def summarize(self, content: str) -> Tuple[str, str]:  # pragma: no cover - protocol
        ...


class NoopSummarizer:
    """Fallback summarizer used when none is injected (yields empty tiers)."""

    def summarize(self, content: str) -> Tuple[str, str]:
        return ("", "")


@dataclass
class TierResult:
    """The derived tiers for one memory (FR-13)."""

    l0_summary: str
    l1_overview: str
    l2_raw: str
    tierable: bool
    summary_generated_at: float


def decide_tierable(content: str) -> bool:
    """Whether ``content`` can be tiered (summarized).

    Free-text memory content is always tierable. Non-text / binary payloads
    would be flagged ``tierable=False`` by the caller (e.g. an attachment whose
    text cannot be extracted) — those hit the FR-16 hard-limit reject path
    instead of being silently truncated.
    """
    return bool(content)


def is_summary_stale(summary_generated_at: float, refresh_days: int, now: float) -> bool:
    """Whether a previously generated summary should be (re)generated (FR-15)."""
    if not summary_generated_at:
        return True
    return (now - summary_generated_at) >= max(1, int(refresh_days)) * SECONDS_PER_DAY


def tier_content(
    content: str,
    summarizer: Optional[Summarizer] = None,
    *,
    l0_summary: str = "",
    l1_overview: str = "",
    tierable: Optional[bool] = None,
    summary_generated_at: float = 0.0,
    refresh_days: int = SUMMARY_REFRESH_DAYS_DEFAULT,
    now: float = 0.0,
    force_refresh: bool = False,
) -> TierResult:
    """Apply the density tier to raw ``content`` (FR-13 / FR-15).

    Resolution order:

    1. ``tierable`` is decided (caller override if given, else ``decide_tierable``).
    2. If tierable and (no L0 yet OR stale OR ``force_refresh``) and a
       ``summarizer`` is available → (re)generate L0/L1 and stamp the time.
    3. Non-tierable content keeps empty derived tiers.
    """
    now = now or time.time()
    can_tier = decide_tierable(content)
    if tierable is not None:
        can_tier = tierable and can_tier

    generated_at = summary_generated_at
    if can_tier and (
        force_refresh
        or not l0_summary
        or is_summary_stale(summary_generated_at, refresh_days, now)
    ):
        # (Re)generate when missing, forced, or the existing summary is stale
        # (FR-15 lazy fallback at read time). Write-time summaries must be passed
        # with a fresh ``summary_generated_at`` so they are not overwritten.
        if summarizer is not None:
            l0_summary, l1_overview = summarizer.summarize(content)
            generated_at = now
        else:
            generated_at = generated_at or 0.0

    if not can_tier:
        # Non-tierable: no derived summaries, no generation timestamp.
        l0_summary, l1_overview = "", ""
        generated_at = 0.0

    return TierResult(
        l0_summary=l0_summary,
        l1_overview=l1_overview,
        l2_raw=content,
        tierable=can_tier,
        summary_generated_at=generated_at,
    )


__all__ = [
    "NoopSummarizer",
    "SECONDS_PER_DAY",
    "SUMMARY_REFRESH_DAYS_DEFAULT",
    "Summarizer",
    "TierResult",
    "decide_tierable",
    "is_summary_stale",
    "tier_content",
]
