"""Index DSH plugin calls for a future administrator audit view."""

from __future__ import annotations

from typing import Any

from app.core.db import get_db


async def index_plugin_calls(
    *, tenant_id: str, user_id: str, conversation_id: str,
    message_id: str, events: list[dict[str, Any]],
) -> None:
    for event in events:
        if event.get("item_kind") != "tool" or event.get("type") not in {"item.completed", "item.failed"}:
            continue
        payload = event.get("payload") or {}
        plugin_name = str(payload.get("plugin_name") or "")
        call_id = str(payload.get("callId") or "")
        if not plugin_name or not call_id:
            continue
        await get_db().plugin_execution_audits.update_one(
            {"_id": f"{tenant_id}:{message_id}:{call_id}"},
            {"$set": {
                "tenant_id": tenant_id, "user_id": user_id,
                "conversation_id": conversation_id, "message_id": message_id,
                "call_id": call_id, "plugin_name": plugin_name,
                "plugin_version": str(payload.get("plugin_version") or ""),
                "plugin_spec": str(payload.get("plugin_spec") or ""),
                "tool_name": str(payload.get("name") or ""),
                "event_id": str(event.get("event_id") or ""),
                "arguments": payload.get("args") if isinstance(payload.get("args"), dict) else {},
                "status": str(payload.get("status") or ""),
                "result_summary": str(payload.get("result_summary") or ""),
                "error": str(payload.get("error") or ""),
                "artifacts": payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else [],
            }}, upsert=True,
        )
