from __future__ import annotations

import asyncio

from app.dsh_runtime.plugin_management import audit


def test_indexes_failed_plugin_call_with_version_and_artifacts(monkeypatch) -> None:
    writes = []

    class Collection:
        async def update_one(self, key, value, upsert):
            writes.append((key, value["$set"], upsert))

    class Database:
        plugin_execution_audits = Collection()

    monkeypatch.setattr(audit, "get_db", Database)
    asyncio.run(audit.index_plugin_calls(
        tenant_id="tenant", user_id="user", conversation_id="conversation",
        message_id="message", events=[
            {"item_kind": "tool", "type": "item.failed", "payload": {
                "callId": "call", "name": "plugin_tool", "plugin_name": "example",
                "plugin_version": "1.2.3", "status": "failed", "error": "failed",
                "artifacts": [{"filename": "middle.txt"}],
            }},
        ],
    ))
    assert writes[0][0]["_id"] == "tenant:message:call"
    assert writes[0][1]["plugin_version"] == "1.2.3"
    assert writes[0][1]["artifacts"][0]["filename"] == "middle.txt"
