"""Mongo-backed CRUD for execution event logs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.tenant import add_tenant_scope, resolve_tenant_id


COLLECTION_NAME = "execution_logs"


class ExecutionEventStore:
    """Version-neutral Motor event store, keyed by session and message."""

    def __init__(self, db: Any, *, collection_name: str, schema_version: int) -> None:
        self._coll = db[collection_name]
        self._schema_version = int(schema_version)

    async def append_events(
        self,
        session_id: str,
        message_id: str,
        events: List[Dict[str, Any]],
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        if not events:
            return
        now = datetime.now(tz=timezone.utc)
        resolved_tenant_id = resolve_tenant_id(tenant_id)
        query = {"session_id": session_id, "message_id": message_id}
        if resolved_tenant_id != "default":
            query["tenant_id"] = resolved_tenant_id
        await self._coll.update_one(
            query,
            {
                "$push": {"events": {"$each": events}},
                "$setOnInsert": {
                    "session_id": session_id,
                    "message_id": message_id,
                    "user_id": user_id,
                    "tenant_id": resolved_tenant_id,
                    "created_at": now,
                    "status": "live",
                    "schema_version": self._schema_version,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    async def get_for_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        return await self._coll.find_one({"message_id": message_id})

    async def get_events_for_message(self, message_id: str) -> List[Dict[str, Any]]:
        doc = await self._coll.find_one(
            {"message_id": message_id},
            projection={"events": 1, "_id": 0},
        )
        return list((doc or {}).get("events") or [])

    async def get_events_for_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return ``{message_id: [events]}`` for one session, in insertion order."""
        cursor = self._coll.find(
            add_tenant_scope({"session_id": session_id}, tenant_id),
            projection={"message_id": 1, "events": 1, "_id": 0},
        ).sort("created_at", 1)
        out: Dict[str, List[Dict[str, Any]]] = {}
        async for doc in cursor:
            mid = str(doc.get("message_id") or "")
            if mid:
                out[mid] = list(doc.get("events") or [])
        return out

    async def replace_events(
        self,
        message_id: str,
        events: List[Dict[str, Any]],
    ) -> None:
        await self._coll.update_one(
            {"message_id": message_id},
            {"$set": {"events": events, "updated_at": datetime.now(tz=timezone.utc)}},
        )

    async def finalize(
        self,
        message_id: str,
        *,
        summary: Dict[str, Any],
        status: str = "completed",
    ) -> None:
        await self._coll.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "summary": summary,
                    "status": status,
                    "finalized_at": datetime.now(tz=timezone.utc),
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            },
        )


class LegacyExecutionLogStore(ExecutionEventStore):
    """Read-only handle for execution logs created before V3 persistence."""

    def __init__(self, db: Any, *, collection_name: str = COLLECTION_NAME, schema_version: int = 2) -> None:
        super().__init__(db, collection_name=collection_name, schema_version=schema_version)
