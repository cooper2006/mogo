"""Tests for the A2A gateway core (feature 012): AgentCard / JSON-RPC / lifecycle."""

from __future__ import annotations

import pytest

from app.a2a.agent_card import (
    A2A_PROTOCOL_VERSION,
    AgentCard,
    AgentCardError,
    AgentSkill,
    build_agent_card,
    parse_agent_card,
)
from app.a2a.protocol import (
    ERROR_CODES,
    ERROR_INVALID_PARAMS,
    ERROR_INVALID_REQUEST,
    ERROR_METHOD_NOT_FOUND,
    ERROR_MOVO_DENIED,
    METHOD_MESSAGE_SEND,
    METHOD_TASKS_GET,
    METHOD_TASKS_RESULT,
    SUPPORTED_METHODS,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    TaskLifecycle,
    TaskState,
    rpc_error_from_denial,
)


# --- AgentCard ---------------------------------------------------------------

def test_agent_card_requires_id_and_name() -> None:
    with pytest.raises(AgentCardError):
        AgentCard(agent_id="", name="x")
    with pytest.raises(AgentCardError):
        AgentCard(agent_id="a", name="")


def test_agent_card_rejects_unknown_auth_method() -> None:
    with pytest.raises(AgentCardError):
        AgentCard(agent_id="a", name="n", auth_method="magic")


def test_agent_card_url_uses_standard_path() -> None:
    card = AgentCard(agent_id="agent-1", name="Sales Agent", tenant_id="t1")
    assert card.url() == "/a2a/t1/agent-1"


def test_agent_card_as_dict_has_required_fields() -> None:
    card = AgentCard(
        agent_id="a",
        name="Agent",
        description="d",
        skills=[AgentSkill(id="s1", name="Query")],
    )
    payload = card.as_dict()
    assert payload["name"] == "Agent"
    assert payload["version"] == A2A_PROTOCOL_VERSION
    assert payload["authentication"]["schemes"] == ["api_key"]
    assert payload["skills"][0]["id"] == "s1"
    assert "inputModes" in payload["skills"][0]


def test_agent_skill_requires_id() -> None:
    with pytest.raises(AgentCardError):
        AgentSkill(id="")


def test_build_agent_card_returns_none_when_not_exposed() -> None:
    assert build_agent_card(agent_id="a", name="A") is None  # a2a_exposed defaults False


def test_build_agent_card_when_exposed() -> None:
    card = build_agent_card(
        agent_id="a",
        name="A",
        a2a_exposed=True,
        capabilities=[{"id": "crm.query", "name": "CRM Query"}],
    )
    assert card is not None
    assert [skill.id for skill in card.skills] == ["crm.query"]


def test_build_agent_card_skips_capabilities_without_id() -> None:
    card = build_agent_card(agent_id="a", name="A", a2a_exposed=True, capabilities=[{"name": "no-id"}])
    assert card is not None and card.skills == []


def test_parse_agent_card_dify_fields() -> None:
    card = parse_agent_card(
        {
            "name": "Remote",
            "description": "d",
            "url": "https://example/a2a",
            "protocolVersion": "1.0",
            "authentication": {"schemes": ["oauth2"]},
            "skills": [{"id": "s1", "name": "S1"}],
        }
    )
    assert card.name == "Remote"
    assert card.endpoint == "https://example/a2a"
    assert card.auth_method == "oauth2"
    assert card.skills[0].id == "s1"


def test_parse_agent_card_tolerates_unknown_auth_scheme() -> None:
    card = parse_agent_card({"name": "R", "authentication": {"schemes": ["mutual_tls"]}})
    assert card.auth_method == "api_key"


def test_parse_agent_card_requires_name() -> None:
    with pytest.raises(AgentCardError):
        parse_agent_card({"description": "no name"})


# --- JSON-RPC request validation ---------------------------------------------

def test_supported_methods_are_the_a2a_three() -> None:
    assert SUPPORTED_METHODS == (METHOD_MESSAGE_SEND, METHOD_TASKS_GET, METHOD_TASKS_RESULT)


def test_request_rejects_bad_jsonrpc_version() -> None:
    error = JsonRpcRequest(method=METHOD_MESSAGE_SEND, jsonrpc="1.0").validate()
    assert error is not None and error.code == ERROR_INVALID_REQUEST


def test_request_rejects_unknown_method() -> None:
    error = JsonRpcRequest(method="tasks/delete").validate()
    assert error is not None and error.code == ERROR_METHOD_NOT_FOUND


def test_request_accepts_valid_method() -> None:
    assert JsonRpcRequest(method=METHOD_MESSAGE_SEND, params={"x": 1}).validate() is None


def test_response_shape_with_result() -> None:
    payload = JsonRpcResponse(id=1, result={"ok": True}).as_dict()
    assert payload["result"] == {"ok": True}
    assert "error" not in payload


def test_response_shape_with_error() -> None:
    payload = JsonRpcResponse(id=1, error=JsonRpcError(ERROR_INVALID_PARAMS, "bad")).as_dict()
    assert payload["error"]["code"] == ERROR_INVALID_PARAMS


def test_rpc_error_from_denial_maps_to_movo_code() -> None:
    error = rpc_error_from_denial(layer="rbac", reason="no code", status_code=403)
    assert error.code == ERROR_MOVO_DENIED
    assert error.data["layer"] == "rbac"
    assert error.data["statusCode"] == 403


def test_error_codes_include_movo_denied() -> None:
    assert ERROR_CODES["movo_denied"] == ERROR_MOVO_DENIED


# --- task lifecycle / idempotency --------------------------------------------

def test_submit_creates_task() -> None:
    lifecycle = TaskLifecycle()
    task, created = lifecycle.submit("t-1", payload={"q": "hi"})
    assert created is True
    assert task["state"] == TaskState.SUBMITTED.value


def test_resubmit_same_id_is_idempotent() -> None:
    lifecycle = TaskLifecycle()
    lifecycle.submit("t-1", payload={"q": "hi"})
    _, created = lifecycle.submit("t-1", payload={"q": "again"})
    assert created is False
    # the original payload is preserved, not overwritten
    assert lifecycle.get("t-1")["payload"] == {"q": "hi"}


def test_complete_and_result() -> None:
    lifecycle = TaskLifecycle()
    lifecycle.submit("t-1")
    lifecycle.complete("t-1", {"answer": 42})
    result = lifecycle.result("t-1")
    assert result is not None
    assert result["state"] == TaskState.COMPLETED.value
    assert result["result"] == {"answer": 42}


def test_fail_records_error() -> None:
    lifecycle = TaskLifecycle()
    lifecycle.submit("t-1")
    lifecycle.fail("t-1", JsonRpcError(ERROR_MOVO_DENIED, "denied"))
    result = lifecycle.result("t-1")
    assert result["state"] == TaskState.FAILED.value
    assert result["error"]["code"] == ERROR_MOVO_DENIED


def test_result_for_unknown_task_is_none() -> None:
    assert TaskLifecycle().result("missing") is None


# --- FR-2 / FR-10: inbound JSON-RPC surface --------------------------------


def _patch_auth(monkeypatch):
    """Mock _resolve_session_user on the auth module so the endpoint's local
    import picks up the fake (no DB needed)."""
    from app.api.endpoints import auth as auth_mod

    async def _fake(authorization=None):
        return {"user": {"_id": "u-test"}, "main_id": "default"}

    monkeypatch.setattr(auth_mod, "_resolve_session_user", _fake)


def test_jsonrpc_message_send_submits_task(monkeypatch):
    """POST /internal/a2a/rpc with message/send creates a task and returns
    the created flag; a replay of the same taskId returns created=False
    (FR-10 idempotency)."""
    import asyncio
    import app.api.endpoints.a2a as a2a_endpoint

    _patch_auth(monkeypatch)
    a2a_endpoint._lifecycle = TaskLifecycle()

    async def _call(payload):
        return await a2a_endpoint.a2a_jsonrpc(payload, authorization="Bearer test")

    result = asyncio.run(_call({"method": "message/send", "id": 1, "params": {"taskId": "task-1", "text": "hello"}}))
    assert result["result"]["created"] is True
    assert result["result"]["state"] == "working"

    # Replay the same taskId — must be idempotent.
    result2 = asyncio.run(_call({"method": "message/send", "id": 2, "params": {"taskId": "task-1"}}))
    assert result2["result"]["created"] is False


def test_jsonrpc_unknown_method_returns_method_not_found(monkeypatch):
    """POST /internal/a2a/rpc with an unsupported method returns
    ERROR_METHOD_NOT_FOUND (FR-7 error mapping)."""
    import asyncio
    import app.api.endpoints.a2a as a2a_endpoint
    from app.a2a.protocol import ERROR_METHOD_NOT_FOUND

    _patch_auth(monkeypatch)
    a2a_endpoint._lifecycle = TaskLifecycle()

    result = asyncio.run(a2a_endpoint.a2a_jsonrpc(
        {"method": "unknown/thing", "id": 99, "params": {}},
        authorization="Bearer test",
    ))
    assert result["error"]["code"] == ERROR_METHOD_NOT_FOUND


def test_jsonrpc_tasks_get_returns_task_state(monkeypatch):
    """POST /internal/a2a/rpc with tasks/get returns the stored task state."""
    import asyncio
    import app.api.endpoints.a2a as a2a_endpoint

    _patch_auth(monkeypatch)
    lifecycle = TaskLifecycle()
    lifecycle.submit("task-x", payload={"text": "test"})
    lifecycle.complete("task-x", {"answer": "ok"})
    a2a_endpoint._lifecycle = lifecycle

    result = asyncio.run(a2a_endpoint.a2a_jsonrpc(
        {"method": "tasks/get", "id": 5, "params": {"taskId": "task-x"}},
        authorization="Bearer test",
    ))
    assert result["result"]["state"] == "completed"


def test_jsonrpc_tasks_result_returns_result_and_error(monkeypatch):
    """POST /internal/a2a/rpc with tasks/result returns the task result
    or error field (FR-10)."""
    import asyncio
    import app.api.endpoints.a2a as a2a_endpoint
    from app.a2a.protocol import JsonRpcError, ERROR_MOVO_DENIED

    _patch_auth(monkeypatch)
    lifecycle = TaskLifecycle()
    lifecycle.submit("ok-task")
    lifecycle.complete("ok-task", {"data": 42})
    lifecycle.submit("bad-task")
    lifecycle.fail("bad-task", JsonRpcError(ERROR_MOVO_DENIED, "denied"))
    a2a_endpoint._lifecycle = lifecycle

    ok = asyncio.run(a2a_endpoint.a2a_jsonrpc(
        {"method": "tasks/result", "id": 1, "params": {"taskId": "ok-task"}},
        authorization="Bearer test",
    ))
    assert ok["result"]["result"] == {"data": 42}
    assert ok["result"]["error"] is None

    bad = asyncio.run(a2a_endpoint.a2a_jsonrpc(
        {"method": "tasks/result", "id": 2, "params": {"taskId": "bad-task"}},
        authorization="Bearer test",
    ))
    assert bad["result"]["error"]["code"] == ERROR_MOVO_DENIED


def test_jsonrpc_invalid_params_rejected(monkeypatch):
    """POST /internal/a2a/rpc with non-dict params returns ERROR_INVALID_PARAMS."""
    import asyncio
    import app.api.endpoints.a2a as a2a_endpoint
    from app.a2a.protocol import ERROR_INVALID_PARAMS

    _patch_auth(monkeypatch)
    a2a_endpoint._lifecycle = TaskLifecycle()

    result = asyncio.run(a2a_endpoint.a2a_jsonrpc(
        {"method": "message/send", "id": 7, "params": "not-a-dict"},
        authorization="Bearer test",
    ))
    assert result["error"]["code"] == ERROR_INVALID_PARAMS
