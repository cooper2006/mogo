"""Linear-timeline invariants + optimistic-lock conflict detection (002 FR-3/FR-4).

The session history is a **hard linear constraint**: ``resume`` never forks, and a
concurrent writer that loses the race re-reads the latest state and retries
(clarify: MongoDB optimistic lock on ``seq``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class LinearTimelineError(ValueError):
    """Raised when an operation would break the linear timeline."""


@dataclass
class Timeline:
    """A monotonically increasing sequence of message positions."""

    seqs: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.seqs = sorted(int(seq) for seq in self.seqs)

    @property
    def max_seq(self) -> int:
        return self.seqs[-1] if self.seqs else 0

    def next_seq(self) -> int:
        """The seq a newly appended message should carry."""
        return self.max_seq + 1

    def resume_from(self, snapshot_seq: int) -> int:
        """The seq continuation point after resuming from ``snapshot_seq``.

        Resume continues *after* the snapshot; it must not reset to 1, or history
        would fork (FR-3).
        """
        if snapshot_seq < 0:
            raise LinearTimelineError("snapshot seq must be >= 0")
        if self.seqs and snapshot_seq > self.max_seq:
            raise LinearTimelineError(
                f"snapshot seq {snapshot_seq} is ahead of current max {self.max_seq}"
            )
        return snapshot_seq + 1

    def append(self, seq: int) -> None:
        """Append a message at ``seq``, rejecting out-of-order / duplicate writes."""
        value = int(seq)
        if self.seqs and value <= self.max_seq:
            raise LinearTimelineError(
                f"seq {value} is not greater than current max {self.max_seq} (would fork)"
            )
        self.seqs.append(value)


@dataclass
class ConflictResult:
    """Outcome of an optimistic-lock write attempt."""

    ok: bool
    expected_seq: int
    actual_seq: int

    @property
    def conflict(self) -> bool:
        return not self.ok


def check_and_advance(
    current_seq: int,
    expected_seq: int,
    *,
    max_retries: int = 3,
    attempts: int = 0,
) -> ConflictResult:
    """Optimistic-lock check: the write succeeds only if ``expected_seq`` matches.

    On conflict the caller is expected to re-read the latest ``current_seq`` and
    retry (FR-4). After ``max_retries`` the caller should fail closed.
    """
    if int(expected_seq) == int(current_seq):
        return ConflictResult(ok=True, expected_seq=int(expected_seq), actual_seq=int(current_seq))
    if attempts >= max_retries:
        raise LinearTimelineError(
            f"seq conflict persisted after {attempts} retries (expected {expected_seq}, actual {current_seq})"
        )
    return ConflictResult(ok=False, expected_seq=int(expected_seq), actual_seq=int(current_seq))


def merge_linear(existing: Iterable[int], incoming: Iterable[int]) -> list[int]:
    """Merge message seqs into a single strictly-increasing timeline.

    Duplicates are dropped (last writer keeps its position); the result is the
    linear history (FR-6), never a branched one.
    """
    seen: set[int] = set()
    merged: list[int] = []
    for seq in list(existing) + list(incoming):
        value = int(seq)
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return sorted(merged)
