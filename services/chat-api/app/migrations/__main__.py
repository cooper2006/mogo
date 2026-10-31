"""Run additive database migrations before a new image replaces the old one."""

from __future__ import annotations

import asyncio
import sys

from app.core.db import close_db, get_db
from app.migrations import session_sharing


async def migrate(db) -> None:
    await session_sharing.migrate(db)


async def _migrate_configured_database() -> None:
    # Motor 2.x binds its client to the loop active at construction time.
    await migrate(get_db())


def main() -> int:
    try:
        asyncio.run(_migrate_configured_database())
    except Exception as exc:
        print(f"Database upgrade stopped before service replacement: {exc}", file=sys.stderr)
        return 1
    finally:
        close_db()
    print("Database indexes are ready; existing documents were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
