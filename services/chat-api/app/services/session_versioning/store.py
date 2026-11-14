"""Snapshot store: commit / log / resume (002 FR-1 / FR-2 / FR-3 / T007-T011).

The store keeps snapshots per session ordered by time, supports listing (``log``)
and resolving a ``resume`` start point. The in-memory implementation here mirrors
the Mongo-backed one (``session_snapshots``); it is intentionally DB-free so the
logic is unit-testable anywhere.

``resume`` continues **after** the chosen snapshot's seq and never resets to 1 —
the linear-timeline guarantee (FR-3).
"""

from __future__ import annotations

from typing import Optional

from .snapshot import SessionSnapshot
from .timeline import Timeline


class SnapshotStore:
    """In-memory snapshot store, scoped per session."""

    def __init__(self) -> None:
        self._by_session: dict[str, list[SessionSnapshot]] = {}
        self._counter = 0

    def commit(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Persist a snapshot (assigning an id if missing)."""
        self._counter += 1
        if not snapshot.snapshot_id:
            snapshot.snapshot_id = f"snap-{self._counter:06d}"
        self._by_session.setdefault(snapshot.session_id, []).append(snapshot)
        return snapshot

    def log(self, session_id: str) -> list[SessionSnapshot]:
        """List a session's snapshots in timeline order (FR-2)."""
        return sorted(self._by_session.get(session_id, []), key=lambda item: item.seq)

    def latest(self, session_id: str) -> Optional[SessionSnapshot]:
        snapshots = self.log(session_id)
        return snapshots[-1] if snapshots else None

    def by_id(self, session_id: str, snapshot_id: str) -> Optional[SessionSnapshot]:
        for snapshot in self.log(session_id):
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        return None

    def resume_point(self, session_id: str, *, snapshot_id: str = "") -> int:
        """The seq a resumed session should continue from (FR-3).

        Resolving to a specific snapshot continues after it; an unknown id falls
        back to the latest snapshot; an empty session resumes at seq 1.
        """
        target = self.by_id(session_id, snapshot_id) if snapshot_id else self.latest(session_id)
        if target is None:
            if snapshot_id:
                raise KeyError(f"snapshot not found: {snapshot_id}")
            return 1
        timeline = Timeline([item.seq for item in self.log(session_id)])
        return timeline.resume_from(target.seq)

    def preview(self, session_id: str, snapshot_id: str = "") -> dict[str, object]:
        """Preview a snapshot's summary without restoring it (FR-2)."""
        target = self.by_id(session_id, snapshot_id) if snapshot_id else self.latest(session_id)
        if target is None:
            return {}
        return {
            "snapshotId": target.snapshot_id,
            "seq": target.seq,
            "trigger": target.trigger,
            "actor": target.actor,
            "summary": target.summary,
            "changedRefs": list(target.changed_refs),
            "attachmentCount": len(target.attachment_refs),
            "createdAt": target.created_at.isoformat(),
        }

    def __len__(self) -> int:
        return sum(len(items) for items in self._by_session.values())
