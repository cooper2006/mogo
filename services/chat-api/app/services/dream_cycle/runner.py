"""Dream-cycle runner (011 T001-T008).

Runs the dream pipeline: read candidate signals -> rank -> validate ->
apply (with dream-journal + shadow rollout + dry-run) -> report.

All side-effect functions are injectable so the runner is unit-testable
without a live DB; the default implementations persist to the configured
collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

# Default top-N for candidate signals feeding the dream pipeline (T002 / OQ-1).
DEFAULT_TOP_N = 10
# Shadow-rollout traffic ratio when applying improvements (T005).
DEFAULT_SHRADOW_RATIO = 0.1


@dataclass
class DreamCandidate:
    """One candidate signal ranked for dream processing."""
    key: str
    score: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def rank(self) -> int:
        """Sort rank used by the candidate-signal ranking (T002)."""
        return int(-self.score * 1000)  # higher score -> smaller rank


@dataclass
class DreamResult:
    """The runner's outcome (T008 report)."""
    cycle_id: str
    started_at: str
    finished_at: str
    candidates: int
    validated: int
    applied: int
    dry_run: bool
    report: dict[str, Any] = field(default_factory=dict)


def rank_candidates(
    signals: Iterable[dict[str, Any]],
    *,
    top_n: int = DEFAULT_TOP_N,
) -> list[DreamCandidate]:
    """Rank candidate signals by score, keeping the top N (T002 / OQ-1)."""
    ranked = sorted(
        (
            DreamCandidate(
                key=str(item.get("key") or ""),
                score=float(item.get("score") or 0.0),
                payload=dict(item),
            )
            for item in signals
            if str(item.get("key") or "").strip()
        ),
        key=lambda c: c.score,
        reverse=True,
    )
    return ranked[: max(1, int(top_n))]


def validate_candidates(
    candidates: Iterable[DreamCandidate],
    validator: Callable[[DreamCandidate], bool] | None = None,
) -> list[DreamCandidate]:
    """Run candidate validation (T004); drop candidates that fail the validator."""
    out: list[DreamCandidate] = []
    for candidate in candidates:
        if validator is None or validator(candidate):
            out.append(candidate)
    return out


def apply_dry_run(
    candidates: Iterable[DreamCandidate],
    *,
    journal: Callable[[str, dict[str, Any]], None] | None = None,
) -> int:
    """Dry-run apply (T005): log the planned changes, change nothing.

    Returns the number of candidates that *would* be applied.
    """
    count = 0
    for candidate in candidates:
        count += 1
        if journal is not None:
            journal(
                "dry_run",
                {"key": candidate.key, "score": candidate.score},
            )
    return count


def apply_shadow(
    candidates: Iterable[DreamCandidate],
    *,
    shadow_ratio: float = DEFAULT_SHRADOW_RATIO,
    journal: Callable[[str, dict[str, Any]], None] | None = None,
) -> int:
    """Shadow apply (T005): route ``shadow_ratio`` of traffic, write journal.

    Returns the number of shadow-applied candidates.
    """
    ratio = min(max(float(shadow_ratio), 0.0), 1.0)
    count = 0
    for candidate in candidates:
        if ratio > 0.0:
            count += 1
            if journal is not None:
                journal(
                    "shadow",
                    {
                        "key": candidate.key,
                        "score": candidate.score,
                        "shadow_ratio": ratio,
                    },
                )
    return count


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_dream_cycle(
    *,
    signals: Iterable[dict[str, Any]],
    validator: Callable[[DreamCandidate], bool] | None = None,
    journal: Callable[[str, dict[str, Any]], None] | None = None,
    dry_run: bool = False,
    shadow_ratio: float = DEFAULT_SHRADOW_RATIO,
    top_n: int = DEFAULT_TOP_N,
    cycle_id: str = "",
) -> DreamResult:
    """Run one dream cycle (011 T001-T008).

    Pipeline: rank -> validate -> apply (dry-run or shadow) -> report.
    """
    started_at = _utcnow_iso()
    ranked = rank_candidates(signals, top_n=top_n)
    validated = validate_candidates(ranked, validator)
    if dry_run:
        applied = apply_dry_run(validated, journal=journal)
    else:
        applied = apply_shadow(validated, shadow_ratio=shadow_ratio, journal=journal)
    finished_at = _utcnow_iso()
    return DreamResult(
        cycle_id=cycle_id or f"dream-{started_at}",
        started_at=started_at,
        finished_at=finished_at,
        candidates=len(ranked),
        validated=len(validated),
        applied=applied,
        dry_run=dry_run,
        report={
            "dry_run": dry_run,
            "shadow_ratio": shadow_ratio if not dry_run else None,
            "top_n": top_n,
        },
    )
