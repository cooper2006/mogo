from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.endpoints import dsh_chat
from app.api.endpoints.dsh_chat import DesktopTurnStartRequest
from app.dsh_runtime.chat_service import DshChatService
from app.governance.topic_admission import TopicAdmissionDenied, TopicAdmissionService


class Policies:
    def __init__(self, rows=None, error=None):
        self.rows = rows or {}
        self.error = error
        self.queries = []

    async def find_one(self, query, projection):
        self.queries.append((query, projection))
        if self.error is not None:
            raise self.error
        return self.rows.get(query["tenant_id"])


def admission(policies: Policies, audience_policy=None) -> TopicAdmissionService:
    return TopicAdmissionService(
        {"topic_admission_policies": policies}, audience_policy=audience_policy,
    )


def test_missing_policy_defaults_off_and_reads_only_the_requested_tenant() -> None:
    policies = Policies({"other": {"mode": "allowlist", "rules": []}})
    assert asyncio.run(admission(policies).evaluate(
        tenant_id="tenant-a", user_id="user-a", text="anything",
    )) == (True, None)
    assert policies.queries == [({"tenant_id": "tenant-a"}, {"mode": 1, "rules": 1})]


def test_allowlist_denylist_disabled_rule_and_audience_filter() -> None:
    rule = {"id": "allowed", "terms": [{"keyword": "知识库"}], "enabled": True}
    disabled = {"id": "disabled", "terms": [{"keyword": "机密"}], "enabled": False}
    policies = Policies({"tenant-a": {"mode": "allowlist", "rules": [rule, disabled]}})
    gate = admission(policies)
    assert asyncio.run(gate.evaluate(
        tenant_id="tenant-a", user_id="user-a", text="查询知识库",
    )) == (True, "allowed")
    with pytest.raises(TopicAdmissionDenied):
        asyncio.run(gate.require(tenant_id="tenant-a", user_id="user-a", text="查询机密"))

    policies.rows["tenant-a"]["mode"] = "denylist"
    with pytest.raises(TopicAdmissionDenied):
        asyncio.run(gate.require(tenant_id="tenant-a", user_id="user-a", text="查询知识库"))
    asyncio.run(gate.require(tenant_id="tenant-a", user_id="user-a", text="查询机密"))

    class Audience:
        async def filter_rules(self, *, main_id, user_id, rules):
            assert (main_id, user_id) == ("tenant-a", "user-b")
            return []

    asyncio.run(admission(policies, Audience()).require(
        tenant_id="tenant-a", user_id="user-b", text="查询知识库",
    ))


def test_database_failure_is_not_treated_as_an_absent_policy() -> None:
    gate = admission(Policies(error=RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(gate.require(tenant_id="tenant-a", user_id="user-a", text="anything"))


def test_real_policy_read_stays_in_the_isolated_test_database(real_mongo_db) -> None:
    harness = real_mongo_db
    harness.run(harness.db.topic_admission_policies.insert_one({
        "tenant_id": "tenant-a", "mode": "allowlist",
        "rules": [{"id": "allowed", "enabled": True, "terms": [{"keyword": "知识库"}]}],
    }))
    gate = TopicAdmissionService(harness.db)
    assert harness.run(gate.evaluate(
        tenant_id="tenant-a", user_id="user-a", text="查询知识库",
    )) == (True, "allowed")
    assert harness.run(gate.evaluate(
        tenant_id="tenant-b", user_id="user-a", text="查询其他内容",
    )) == (True, None)


def test_server_turn_without_an_injected_gate_fails_before_claiming() -> None:
    empty = SimpleNamespace()
    chat = DshChatService(
        gateway=empty, coordinator=empty, conversations=empty, bindings=empty,
        events=empty, profiles=empty, kernel_version="test",
    )
    with pytest.raises(RuntimeError, match="topic admission is not configured"):
        asyncio.run(chat.prepare_turn(
            tenant_id="tenant-a", user_id="user-a", conversation_id=None,
            text="anything", model_instance_id=None, timezone_name=None,
            images=[], documents=[],
        ))


def test_desktop_turn_uses_the_same_explicit_gate_before_starting(monkeypatch) -> None:
    rule = {"id": "blocked", "terms": [{"keyword": "机密"}], "enabled": True}
    gate = admission(Policies({"tenant-a": {"mode": "denylist", "rules": [rule]}}))
    starts = []

    async def identity(_authorization):
        return "tenant-a", "user-a", {}

    async def capability(_tenant_id, _user_id, _accept_language):
        return None

    class Bindings:
        async def start_turn(self, **kwargs):
            starts.append(kwargs)
            return {"started": True}

    monkeypatch.setattr(dsh_chat, "_identity", identity)
    monkeypatch.setattr(dsh_chat, "_require_code_capability", capability)
    monkeypatch.setattr(dsh_chat.dsh_runtime_application, "topic_admission", gate)
    monkeypatch.setattr(dsh_chat.dsh_runtime_application, "desktop_bindings", Bindings())

    async def run(text):
        return await dsh_chat.desktop_turn_start(
            "session-a", DesktopTurnStartRequest(
                device_id="device-a", message_id="message-a", text=text,
            ), authorization=None,
        )

    with pytest.raises(HTTPException) as denied:
        asyncio.run(run("查看机密"))
    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "topic_admission_denied"
    assert starts == []

    assert asyncio.run(run("查看知识库")).data == {"started": True}
    assert len(starts) == 1
