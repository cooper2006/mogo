"""012 T010 US2 tests: outbound A2A call + JSON-RPC error-code mapping + failover."""

from __future__ import annotations

import asyncio

from app.a2a.client import A2AClient, ClientConfig, map_error_code
from app.a2a.protocol import (
    ERROR_INTERNAL,
    ERROR_MOVO_DENIED,
    JsonRpcError,
    JsonRpcResponse,
)
from app.services.dag.retry import RetryPolicy


def _config(primary="primary", backups=("backup",)):
    return ClientConfig(
        primary_agent=primary,
        backup_agents=backups,
        timeout_seconds=30.0,
        retry=RetryPolicy(max_attempts=2, base_seconds=0.1, factor=2.0, cap_seconds=1.0),
    )


def test_outbound_call_succeeds_on_primary():
    async def transport(agent, method, params, timeout):
        assert agent == "primary"
        assert method == "message/send"
        assert timeout == 30.0
        return JsonRpcResponse(id=1, result={"taskState": "working"})

    client = A2AClient(transport, _config())
    call = asyncio.run(client.send({"text": "hi"}, task_id="t-1"))
    assert call.is_ok() is True
    assert call.agent_name == "primary"
    assert call.attempts == 1
    assert call.response.result == {"taskState": "working"}


def test_failover_to_backup_when_primary_unreachable():
    calls: list[str] = []

    async def transport(agent, method, params, timeout):
        calls.append(agent)
        if agent == "primary":
            raise ConnectionError("primary unreachable")
        return JsonRpcResponse(id=1, result={"taskState": "working"})

    client = A2AClient(transport, _config())
    call = asyncio.run(client.send({"text": "hi"}, task_id="t-1"))
    # primary failed -> failed over to backup
    assert call.is_ok() is True
    assert call.agent_name == "backup"
    assert call.failed_over_to == "backup"
    assert "primary" in calls and "backup" in calls


def test_all_agents_exhausted_returns_internal_error():
    async def transport(agent, method, params, timeout):
        raise ConnectionError(f"{agent} down")

    client = A2AClient(transport, _config())
    call = asyncio.run(client.send({"text": "hi"}, task_id="t-1"))
    assert call.is_ok() is False
    assert call.error is not None
    assert call.error.code == ERROR_INTERNAL
    # primary retried 2 attempts, then backup retried 2 attempts
    assert call.attempts == 4


def test_governance_denial_not_retried_not_failover():
    denial = JsonRpcError(ERROR_MOVO_DENIED, "调用被治理层拒绝", data={"layer": "gatekeeper", "reason": "rbac"})

    async def transport(agent, method, params, timeout):
        if agent == "primary":
            # A governance denial is carried on the response, not raised.
            return JsonRpcResponse(id=1, error=denial)
        raise AssertionError("should not fail over on a governance denial")

    client = A2AClient(transport, _config())
    call = asyncio.run(client.send({"text": "hi"}, task_id="t-1"))
    # A denial surfaces immediately with its JSON-RPC code; no retry, no failover.
    assert call.is_ok() is False
    assert call.error is not None
    assert call.error.code == ERROR_MOVO_DENIED
    assert call.agent_name == "primary"
    assert call.failed_over_to == ""
    assert call.attempts == 1


def test_error_code_mapping():
    assert map_error_code(JsonRpcError(ERROR_MOVO_DENIED, "denied")) == ERROR_MOVO_DENIED
    assert map_error_code(PermissionError("denied")) == ERROR_MOVO_DENIED
    assert map_error_code(RuntimeError("boom")) == ERROR_INTERNAL
    assert map_error_code(JsonRpcError(ERROR_INTERNAL, "x")) == ERROR_INTERNAL


def test_outbound_call_document_serialisable():
    async def transport(agent, method, params, timeout):
        return JsonRpcResponse(id=1, result={"ok": True})

    client = A2AClient(transport, _config())
    call = asyncio.run(client.send({"text": "hi"}, task_id="t-9"))
    doc = call.as_document()
    assert doc["ok"] is True
    assert doc["agent"] == "primary"
    assert doc["method"] == "message/send"
    assert doc["task_id"] == "t-9"
    assert "result" in doc


def test_default_timeout_is_30_seconds():
    from app.a2a.client import DEFAULT_TIMEOUT_SECONDS

    assert DEFAULT_TIMEOUT_SECONDS == 30.0
    config = _config()
    assert config.timeout_seconds == 30.0
