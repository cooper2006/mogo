"""001 employee-side internal gatekeeper endpoint.

Covers the wiring that makes the six-layer chain actually reachable from chat-api:
service-token auth, position-role resolution (the RBAC source that was broken),
and the redacted request body handed back to the caller (FR-7).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.routes import gatekeeper_internal as endpoint
from app.core.config import settings


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=0):
        return list(self._rows)


class _FakeCollection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, flt, projection=None):
        out = [
            r
            for r in self._rows
            if all(r.get(k) == v for k, v in flt.items())
        ]
        return _FakeCursor(out)


class _FakeDb:
    def __init__(self, roles):
        self._roles = roles

    def __getitem__(self, name):
        if name == "end_user_position_roles":
            return _FakeCollection(self._roles)
        raise AssertionError(f"unexpected collection {name}")


def test_require_service_rejects_a_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)
    with pytest.raises(HTTPException) as exc:
        endpoint._require_service("")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        endpoint._require_service("wrong")
    endpoint._require_service("s3cret")  # correct token passes


def test_resolve_roles_reads_the_employee_bindings(monkeypatch):
    """RBAC's role source: 006 binds roles to employees in end_user_position_roles."""
    db = _FakeDb(
        [
            {"tenant_id": "t1", "user_id": "u1", "role_id": "system:t1:editor"},
            {"tenant_id": "t1", "user_id": "u1", "role_id": "system:t1:viewer"},
            {"tenant_id": "t1", "user_id": "u2", "role_id": "system:t1:other"},
        ]
    )
    monkeypatch.setattr("app.core.db.get_db", lambda: db, raising=False)
    roles = asyncio.run(endpoint._resolve_roles("t1", "u1", []))
    assert sorted(roles) == ["system:t1:editor", "system:t1:viewer"]


def test_resolve_roles_prefers_provided_roles(monkeypatch):
    roles = asyncio.run(endpoint._resolve_roles("t1", "u1", ["explicit"]))
    assert roles == ["explicit"]


def test_evaluate_returns_the_verdict_and_redacted_request(monkeypatch):
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)

    captured = {}

    class _Verdict:
        decision = type("D", (), {"value": "allow"})()
        layer = "gatekeeper"
        reason = "all layers passed"
        status_code = 200
        detail: dict = {}

    async def _fake_evaluate(tool, ctx):
        captured["tool"] = tool
        captured["roles"] = list(ctx.roles)
        # Simulate the redaction layer rewriting the request in place.
        ctx.request["note"] = "[REDACTED]"
        return _Verdict()

    class _FakeGatekeeper:
        async def evaluate(self, tool, ctx):
            return await _fake_evaluate(tool, ctx)

    monkeypatch.setattr(endpoint, "gatekeeper", _FakeGatekeeper())
    monkeypatch.setattr(
        endpoint, "_resolve_roles", lambda *a, **k: _async(["role-x"])
    )

    payload = endpoint.GateEvaluatePayload(
        tool="web.search",
        tenantId="t1",
        userId="u1",
        request={"note": "secret-value"},
    )
    result = asyncio.run(endpoint.evaluate_gate(payload, service_token="s3cret"))
    data = result["data"]
    assert data["decision"] == "allow"
    # The (redacted) request is handed back so plaintext never reaches the backend.
    assert data["request"]["note"] == "[REDACTED]"
    assert captured["tool"] == "web.search"
    assert captured["roles"] == ["role-x"]


def _async(value):
    async def _inner(*_a, **_k):
        return value

    return _inner()


def test_evaluate_injects_the_approval_ticket_annotation(monkeypatch):
    """FR-2 resume: the token a caller carries must reach the approval layer."""
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)
    captured = {}

    class _Verdict:
        decision = type("D", (), {"value": "allow"})()
        layer = "approval"
        reason = "approval token consumed"
        status_code = 200
        detail: dict = {}

    class _FakeGatekeeper:
        async def evaluate(self, tool, ctx):
            captured.update(ctx.annotations)
            return _Verdict()

    monkeypatch.setattr(endpoint, "gatekeeper", _FakeGatekeeper())
    monkeypatch.setattr(endpoint, "_resolve_roles", lambda *a, **k: _async([]))

    payload = endpoint.GateEvaluatePayload(
        tool="browser",
        tenantId="t1",
        userId="u1",
        sessionId="s1",
        approvalToken="tok-1",
        approvalActionId="a1",
    )
    asyncio.run(endpoint.evaluate_gate(payload, service_token="s3cret"))
    assert captured["approval_token"] == "tok-1"
    assert captured["approval_action_id"] == "a1"


def test_decide_endpoint_requires_the_service_token(monkeypatch):
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)
    payload = endpoint.GateApprovalDecision(actionId="a1", token="t", approved=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint.decide_gate_approval(payload, service_token="wrong"))
    assert exc.value.status_code == 401


def test_decide_endpoint_moves_the_ticket(monkeypatch):
    """A human approver approves; an unknown/expired ticket is a 404."""
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)

    from app.governance.layers import approval as approval_module

    class _Registry:
        def __init__(self, *a, **k):
            pass

        async def decide(self, *, action_id, token, approved, actor=""):
            return action_id == "known"

    monkeypatch.setattr(approval_module, "ApprovalRegistry", _Registry)

    ok = asyncio.run(
        endpoint.decide_gate_approval(
            endpoint.GateApprovalDecision(actionId="known", token="t", approved=True, actor="mgr"),
            service_token="s3cret",
        )
    )
    assert ok["data"]["status"] == "approved"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            endpoint.decide_gate_approval(
                endpoint.GateApprovalDecision(actionId="unknown", token="t", approved=True),
                service_token="s3cret",
            )
        )
    assert exc.value.status_code == 404


def test_list_gate_events_is_the_missing_consumer(monkeypatch):
    """The audit trail must be readable — it was write-only before 2026-10-03."""
    monkeypatch.setattr(settings, "backend_service_token", "s3cret", raising=False)

    from app.governance.layers import audit as audit_module

    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        def sort(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        async def to_list(self, length=0):
            return list(self._rows)

    class _Col:
        def find(self, flt, projection=None):
            return _Cursor(
                [
                    {
                        "tenant_id": "t1",
                        "decision": "deny",
                        "tool": "browser",
                        "layer": "rbac",
                        "reason": "no grant",
                    }
                ]
            )

    class _Db:
        def __getitem__(self, name):
            assert name == audit_module.GATE_EVENTS_COLLECTION
            return _Col()

    monkeypatch.setattr("app.core.db.get_db", lambda: _Db(), raising=False)
    result = asyncio.run(
        endpoint.list_gate_events(tenantId="t1", decision="deny", service_token="s3cret")
    )
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0]["layer"] == "rbac"
