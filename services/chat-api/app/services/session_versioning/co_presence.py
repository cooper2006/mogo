"""Concurrent-presence + linear merge helpers (002 US5 / FR-5).

Short-poll presence backed by a MongoDB heartbeat document (no Redis — FR-5).
Offline editors' *contributions* were already merged into the linear timeline
(FR-5: "offline contributions retained"), so presence is *current* only: an
editor is online when its heartbeat is younger than the TTL.

The in-memory fallback below is used when no Mongo is available (dev/tests);
its semantics match the Mongo-backed store exactly.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .timeline import Timeline, merge_linear

DEFAULT_HEARTBEAT_TTL_SECONDS = 30.0


class CoPresence:
    """MongoDB-backed (or in-memory) short-poll presence + message merge.

    - presence: ``heartbeat`` refreshes an editor's TTL; ``online`` returns the
      editors whose heartbeat is fresh (US5).
    - merge:    ``merge_messages`` collapses two concurrent writes into one
      strictly-increasing linear timeline (FR-5 / FR-3), never forking.
    """

    def __init__(self, db: Optional[Any] = None, heartbeat_ttl: float = DEFAULT_HEARTBEAT_TTL_SECONDS) -> None:
        self._db = db
        self._heartbeat_ttl = float(heartbeat_ttl)
        # In-memory fallback for tests / dev.
        self._beats: dict[str, dict[str, float]] = {}
        # In-memory persistence for the in-memory (db=None) merge path:
        self._seq_state: dict[str, list[int]] = {}

    # --- presence (US5) ------------------------------------------------------

    async def heartbeat(self, session_id: str, user_id: str, *, now: float | None = None) -> None:
        beat = time.monotonic() if now is None else now
        if self._db is not None:
            # Mongo-backed: one heartbeat document per (session, user).
            coll = self._db["presence_heartbeats"]
            await coll.update_one(
                {"session_id": session_id, "user_id": user_id},
                {"$set": {"last_beat": beat, "updated_at": beat}},
                upsert=True,
            )
            return
        self._beats.setdefault(session_id, {})[user_id] = beat

    async def online(self, session_id: str, *, now: float | None = None) -> set[str]:
        """The editors currently online (heartbeat younger than the TTL).

        Offline editors are dropped (their contributions were already merged —
        FR-5 retains them on the timeline; presence is *current* only).
        """
        deadline = (now if now is not None else time.monotonic()) - self._heartbeat_ttl
        if self._db is not None:
            coll = self._db["presence_heartbeats"]
            # Mongo-backed: a heartbeat document stores ``last_beat``; a short
            # poll finds the fresh ones. The in-memory fake mirrors this.
            cursor = coll.find({"session_id": session_id})
            if hasattr(cursor, "to_list"):
                rows = await cursor.to_list(length=200)
            else:
                rows = list(cursor)
            online = set()
            for row in rows:
                last_beat = row.get("last_beat")
                if last_beat is None or last_beat >= deadline:
                    online.add(str(row.get("user_id")))
            return online
        members = {
            user
            for user, last_beat in self._beats.get(session_id, {}).items()
            if last_beat >= deadline
        }
        return members

    async def merge_messages(self, session_id: str, incoming: list[int]) -> list[int]:
        """Fold ``incoming`` seqs into the session's linear timeline.

        Concurrent writers each re-read the latest state and merge; the result
        is a strictly-increasing seq list — no fork (FR-3 / FR-5).
        """
        existing = await self._existing_seqs(session_id)
        merged = merge_linear(existing, incoming)
        # Persist the merge (so the next writer re-reads the same linear state).
        if self._db is not None:
            await self._db["session_presence_state"].update_one(
                {"session_id": session_id},
                {"$set": {"seqs": merged}},
                upsert=True,
            )
        else:
            self._seq_state[session_id] = merged
        return merged

    async def _existing_seqs(self, session_id: str) -> list[int]:
        if self._db is not None:
            row = await self._db["session_presence_state"].find_one({"session_id": session_id})
            return [int(seq) for seq in (row or {}).get("seqs", [])]
        return list(self._seq_state.get(session_id, []))

    # --- convenience: build a timeline for inspection ------------------------

    async def timeline(self, session_id: str) -> Timeline:
        return Timeline(seqs=await self._existing_seqs(session_id))
