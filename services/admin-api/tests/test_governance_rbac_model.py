"""Unit tests for the RBAC permission-code model (governance, feature 001 T009)."""

import pytest

from app.governance.rbac_model import (
    PermissionCode,
    expand_role_to_codes,
    has_permission,
    parse_codes,
    required_code_for_tool,
)


def test_parse_simple_and_targeted_codes() -> None:
    assert PermissionCode.parse("knowledge:read").resource == "knowledge"
    assert PermissionCode.parse("knowledge:read").action == "read"
    assert PermissionCode.parse("document:read:doc-1").target == "doc-1"


@pytest.mark.parametrize("bad", ["", "knowledge", ":", "  ", "a:"])
def test_parse_rejects_malformed_codes(bad: str) -> None:
    with pytest.raises(ValueError):
        PermissionCode.parse(bad)


def test_parse_codes_drops_invalid_entries() -> None:
    assert parse_codes(["knowledge:read", "broken", "tool:execute"]) == {
        "knowledge:read",
        "tool:execute",
    }


def test_full_access_role_expands_to_wildcard() -> None:
    assert expand_role_to_codes({"system_key": "full_access_admin"}) == {"*"}


def test_role_expands_capabilities_to_codes() -> None:
    codes = expand_role_to_codes(
        {"capabilities": {"content_generation": True, "code_generation": False}}
    )
    assert "content:generate" in codes
    assert "code:execute" not in codes


def test_has_permission_exact_match() -> None:
    assert has_permission({"knowledge:read"}, "knowledge:read")


def test_has_permission_wildcard_grants_all() -> None:
    assert has_permission({"*"}, "admin:role:assign")


def test_has_permission_resource_wildcard() -> None:
    assert has_permission({"knowledge:*"}, "knowledge:read")


def test_has_permission_rejects_when_missing() -> None:
    assert not has_permission({"knowledge:read"}, "admin:role:assign")


def test_has_permission_unknown_required_fails_closed() -> None:
    assert not has_permission({"*"}, "")  # empty required -> never allowed
    assert not has_permission({"knowledge:read"}, "malformed")


def test_has_permission_target_mismatch() -> None:
    assert not has_permission({"document:read:doc-1"}, "document:read:doc-2")


def test_required_code_for_tool_defaults() -> None:
    assert required_code_for_tool("crm") == "crm:execute"
    assert required_code_for_tool("crm", "read", "acct-1") == "crm:read:acct-1"


def test_admin_tool_calls_fall_back_to_the_full_access_preset(monkeypatch):
    """001 audit (2026-10-03): admin accounts have no position-role bindings.

    Admin console tool calls must run under the tenant's full-access preset instead
    of an empty role set — otherwise the RBAC layer fails closed on every call.
    """
    import asyncio

    from app.api.routes import tools as tools_module

    captured = {}

    class _Verdict:
        decision = type("D", (), {"value": "allow"})()
        layer = "gatekeeper"
        reason = "all layers passed"
        status_code = 200
        detail: dict = {}
        allowed = True

    class _FakeGatekeeper:
        async def evaluate(self, tool, ctx):
            captured["roles"] = list(ctx.roles)
            return _Verdict()

    async def _no_risk(*, tenant_id, tool):
        return "R1"

    monkeypatch.setattr(tools_module, "gatekeeper", _FakeGatekeeper())
    monkeypatch.setattr(
        "app.governance.risk.risk_level_for", _no_risk, raising=False
    )

    asyncio.run(
        tools_module._enforce_gate(
            "tool-1", "t1", {"user_id": "admin-1"}, {"q": "x"}
        )
    )
    assert captured["roles"] == ["system:t1:full_access_admin"]
