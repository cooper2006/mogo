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
