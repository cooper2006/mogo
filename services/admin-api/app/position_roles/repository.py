from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from app.core.db import get_db
from .constants import (
    AGENT_CAPABILITY_KEYS,
    AUDIT_COLLECTION,
    FULL_ACCESS_ROLE_KEY,
    FULL_ACCESS_ROLE_NAME,
    MIGRATION_COLLECTION,
    POSITION_ROLE_COLLECTION,
    USER_OVERRIDE_COLLECTION,
    USER_ROLE_COLLECTION,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PositionRoleRepository:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db if db is not None else get_db()

    async def ensure_indexes(self) -> None:
        await self.db[POSITION_ROLE_COLLECTION].create_index(
            [("main_id", 1), ("name", 1)], unique=True, name="position_role_main_name_unique"
        )
        await self.db[POSITION_ROLE_COLLECTION].create_index(
            [("main_id", 1), ("system_key", 1)],
            unique=True,
            partialFilterExpression={"system_key": {"$exists": True, "$type": "string"}},
            name="position_role_main_system_unique",
        )
        await self.db[USER_ROLE_COLLECTION].create_index(
            [("main_id", 1), ("user_id", 1), ("role_id", 1)], unique=True, name="user_position_role_unique"
        )
        await self.db[USER_ROLE_COLLECTION].create_index(
            [("main_id", 1), ("role_id", 1)], name="position_role_members"
        )
        await self.db[USER_OVERRIDE_COLLECTION].create_index(
            [("main_id", 1), ("user_id", 1), ("expires_at", 1)], name="user_capability_override_active"
        )
        await self.db[MIGRATION_COLLECTION].create_index("main_id", unique=True, name="position_role_migration_main")
        await self.db[AUDIT_COLLECTION].create_index(
            [("main_id", 1), ("created_at", -1)], name="position_role_audit_main_created"
        )

    async def ensure_full_access_role(self, main_id: str) -> dict[str, Any]:
        now = utcnow()
        role_id = f"system:{main_id}:{FULL_ACCESS_ROLE_KEY}"
        await self.db[POSITION_ROLE_COLLECTION].update_one(
            {"main_id": main_id, "system_key": FULL_ACCESS_ROLE_KEY},
            {
                "$setOnInsert": {
                    "_id": role_id,
                    "main_id": main_id,
                    "name": FULL_ACCESS_ROLE_NAME,
                    "description": "系统保障角色，自动拥有企业全部 Agent 能力、工具与 Skill。",
                    "created_at": now,
                },
                "$set": {
                    "status": "active",
                    "protected": True,
                    "capabilities": {key: True for key in AGENT_CAPABILITY_KEYS},
                    "tool_access_mode": "all",
                    "tool_ids": [],
                    "skill_access_mode": "all",
                    "skill_ids": [],
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        return dict(await self.db[POSITION_ROLE_COLLECTION].find_one({"main_id": main_id, "system_key": FULL_ACCESS_ROLE_KEY}))

    async def assign_role(self, main_id: str, user_id: str, role_id: str, *, primary: bool, actor: str) -> None:
        now = utcnow()
        if primary:
            await self.db[USER_ROLE_COLLECTION].update_many(
                {"main_id": main_id, "user_id": user_id}, {"$set": {"is_primary": False, "updated_at": now}}
            )
        await self.db[USER_ROLE_COLLECTION].update_one(
            {"main_id": main_id, "user_id": user_id, "role_id": role_id},
            {
                "$setOnInsert": {"created_at": now, "created_by": actor},
                "$set": {"is_primary": primary, "updated_at": now, "updated_by": actor},
            },
            upsert=True,
        )

    async def complete_migration(self, main_id: str, actor: str) -> None:
        now = utcnow()
        await self.db[MIGRATION_COLLECTION].update_one(
            {"main_id": main_id},
            {
                "$set": {
                    "status": "complete",
                    "completed_at": now,
                    "completed_by": actor,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def replace_user_roles(self, main_id: str, user_id: str, role_ids: list[str], primary_role_id: str, *, actor: str) -> None:
        now = utcnow()
        await self.db[USER_ROLE_COLLECTION].delete_many({"main_id": main_id, "user_id": user_id})
        if role_ids:
            await self.db[USER_ROLE_COLLECTION].insert_many([
                {
                    "main_id": main_id,
                    "user_id": user_id,
                    "role_id": role_id,
                    "is_primary": role_id == primary_role_id,
                    "created_by": actor,
                    "updated_by": actor,
                    "created_at": now,
                    "updated_at": now,
                }
                for role_id in dict.fromkeys(role_ids)
            ])

    async def bulk_replace_user_roles(
        self,
        main_id: str,
        assignments: list[dict[str, Any]],
        *,
        actor: str,
    ) -> int:
        """Atomic bulk replace: one bulk_write for all user-role replacements.

        Each assignment dict must have: user_id, role_ids, primary_role_id.
        Returns the number of users processed.
        """
        if not assignments:
            return 0
        now = utcnow()
        ops: list[Any] = []
        for a in assignments:
            user_id = str(a["user_id"])
            role_ids = [str(r) for r in dict.fromkeys(a.get("role_ids") or [])]
            primary = str(a.get("primary_role_id") or "")
            # Match existing docs for this user so we can replace them atomically.
            ops.append(self.db[USER_ROLE_COLLECTION].delete_many({
                "main_id": main_id, "user_id": user_id,
            }))
            for rid in role_ids:
                ops.append(self.db[USER_ROLE_COLLECTION].insert_one({
                    "main_id": main_id,
                    "user_id": user_id,
                    "role_id": rid,
                    "is_primary": rid == primary,
                    "created_by": actor,
                    "updated_by": actor,
                    "created_at": now,
                    "updated_at": now,
                }))
        # Execute all within a single ordered bulk write (atomic per-user, ordered across ops).
        result = await self.db[USER_ROLE_COLLECTION].bulk_write(ops, ordered=True)
        return result.deleted_count + result.upserted_count

    async def audit(self, main_id: str, actor: str, action: str, target_type: str, target_id: str, details: dict[str, Any]) -> None:
        await self.db[AUDIT_COLLECTION].insert_one({
            "_id": uuid.uuid4().hex,
            "main_id": main_id,
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details,
            "created_at": utcnow(),
        })
