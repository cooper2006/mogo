#!/usr/bin/env python3
"""Attribute old DSH usage rows to the speaker recorded on their kernel binding.

Dry-run by default. Pass one tenant and --apply after reviewing the counts.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import close_db, get_db  # noqa: E402


async def backfill(tenant_id: str, *, apply: bool) -> tuple[int, int, int]:
    db = get_db()
    usage = db.token_usage_logs
    missing_user = {"$in": ["", None]}
    base_match = {"tenant_id": tenant_id, "stage": "dsh_agent_turn", "user_id": missing_user}
    scanned = recoverable = updated = 0

    groups = usage.aggregate([
        {"$match": base_match},
        {"$group": {"_id": "$session_id", "count": {"$sum": 1}}},
    ])
    async for group in groups:
        session_id = str(group.get("_id") or "")
        scanned += int(group.get("count") or 0)
        if not session_id:
            continue
        binding = await db.agent_kernel_bindings.find_one(
            {"tenant_id": tenant_id, "kernel_session_id": session_id},
            {"user_id": 1},
        )
        user_id = str((binding or {}).get("user_id") or "")
        if not ObjectId.is_valid(user_id):
            continue
        user = await db.end_users.find_one({"_id": ObjectId(user_id), "tenant_id": tenant_id}, {"_id": 1})
        if user is None:
            continue
        count = int(group.get("count") or 0)
        recoverable += count
        if apply:
            result = await usage.update_many(
                {**base_match, "session_id": session_id},
                {"$set": {"user_id": user_id}},
            )
            updated += result.modified_count

    return scanned, recoverable, updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="Tenant to repair")
    parser.add_argument("--apply", action="store_true", help="Write the recoverable user IDs")
    args = parser.parse_args()
    try:
        scanned, recoverable, updated = asyncio.run(backfill(args.tenant_id, apply=args.apply))
        print(f"scanned={scanned} recoverable={recoverable} updated={updated} skipped={scanned - recoverable}")
        if not args.apply:
            print("dry run; pass --apply to write")
    finally:
        close_db()


if __name__ == "__main__":
    main()
