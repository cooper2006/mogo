"""Repair duplicate per-session message sequence numbers during maintenance.

The caller must stop the only writer (chat-api) and take a MongoDB archive
first. This module changes ordering metadata only; it never removes messages.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient

from app.migrations.sequence_index import MESSAGE_SEQ_INDEX_FILTER


def _affected_sessions(db: Any) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": MESSAGE_SEQ_INDEX_FILTER},
        {"$group": {
            "_id": {"tenant_id": "$tenant_id", "session_id": "$session_id", "seq": "$seq"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$group": {"_id": {"tenant_id": "$_id.tenant_id", "session_id": "$_id.session_id"}}},
    ]
    return [row["_id"] for row in db.chat_messages.aggregate(pipeline, allowDiskUse=True)]


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def timestamp(row: dict[str, Any]) -> datetime:
        value = row.get("created_at")
        if not isinstance(value, datetime):
            return datetime.min
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        seq = row.get("seq")
        return (
            seq if isinstance(seq, int) and not isinstance(seq, bool) else float("inf"),
            timestamp(row),
            str(row["_id"]),
        )

    return sorted(rows, key=key)


def _remap_boundary(
    rows: list[dict[str, Any]], new_seq: dict[Any, int], start: int, end: int
) -> tuple[int, int]:
    covered = [
        new_seq[row["_id"]]
        for row in rows
        if isinstance(row.get("seq"), int) and start <= row["seq"] <= end
    ]
    if not covered:
        raise ValueError(f"summary covers an empty sequence range: {start}..{end}")
    return min(covered), max(covered)


def _repair_session(db: Any, *, tenant_id: str, session_id: Any) -> int:
    query = {"tenant_id": tenant_id, "session_id": session_id}
    rows = _ordered_rows(list(db.chat_messages.find(query)))
    if not rows:
        raise ValueError(f"conflicting session has no messages: {session_id}")
    new_seq = {row["_id"]: index for index, row in enumerate(rows, 1)}
    unchanged_fields = {
        row["_id"]: {key: value for key, value in row.items() if key not in ("seq", "covers")}
        for row in rows
    }
    summaries: dict[Any, dict[str, int]] = {}
    for row in rows:
        covers = row.get("covers")
        if covers is None:
            continue
        if (
            not isinstance(covers, dict)
            or not isinstance(covers.get("start_seq"), int)
            or not isinstance(covers.get("end_seq"), int)
        ):
            raise ValueError(f"unsupported summary range in message {row['_id']}")
        start, end = _remap_boundary(rows, new_seq, covers["start_seq"], covers["end_seq"])
        summaries[row["_id"]] = {**covers, "start_seq": start, "end_seq": end}

    participants = list(db.session_participants.find({
        "tenant_id": tenant_id,
        "conversation_id": str(session_id),
    }))
    cursors = {}
    for participant in participants:
        old_cursor = int(participant.get("last_read_seq") or 0)
        cursors[participant["_id"]] = max(
            (
                new_seq[row["_id"]]
                for row in rows
                if isinstance(row.get("seq"), int) and row["seq"] <= old_cursor
            ),
            default=0,
        )

    # Two passes avoid transient key collisions if another unique index exists.
    for row in rows:
        db.chat_messages.update_one({"_id": row["_id"]}, {"$unset": {"seq": ""}})
    for row in rows:
        patch: dict[str, Any] = {"seq": new_seq[row["_id"]]}
        if row["_id"] in summaries:
            patch["covers"] = summaries[row["_id"]]
        db.chat_messages.update_one({"_id": row["_id"]}, {"$set": patch})
    db.chat_sessions.update_one(
        {"_id": session_id, "tenant_id": tenant_id},
        {"$set": {"next_message_seq": len(rows)}},
    )
    for participant in participants:
        db.session_participants.update_one(
            {"_id": participant["_id"]}, {"$set": {"last_read_seq": cursors[participant["_id"]]}}
        )
    actual = list(db.chat_messages.find(query).sort("seq", 1))
    if len(actual) != len(rows) or [row.get("seq") for row in actual] != list(range(1, len(rows) + 1)):
        raise RuntimeError(f"sequence verification failed for session {session_id}")
    for row in actual:
        stable = {key: value for key, value in row.items() if key not in ("seq", "covers")}
        if stable != unchanged_fields[row["_id"]]:
            raise RuntimeError(f"message content verification failed for {row['_id']}")
    return len(rows)


def main() -> int:
    if os.environ.get("MOGO_SESSION_FIX_WRITES_STOPPED") != "1":
        print("Refusing sequence repair without the maintenance write-stop flag.", file=sys.stderr)
        return 2
    client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)
    try:
        db = client[os.environ["MONGODB_DB"]]
        affected = _affected_sessions(db)
        for key in affected:
            count = _repair_session(db, **key)
            print(f"Repaired {count} messages in session {key['session_id']}.")
        if _affected_sessions(db):
            raise RuntimeError("duplicate sequence numbers remain after repair")
        print(f"Verified {len(affected)} repaired sessions; no duplicate sequence numbers remain.")
        return 0
    except Exception as exc:
        print(f"Sequence repair failed; restore the backup before restarting chat-api: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
