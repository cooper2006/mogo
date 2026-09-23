"""018 T012 US2 tests: governance view + status + a2a_exposed marking."""

from __future__ import annotations

import pytest

from app.services.capability_assets import CapabilityAssetRegistry, VALID_STATUSES


def test_governance_view_lists_all_assets():
    registry = CapabilityAssetRegistry()
    registry.register(key="tool.alpha", display_name="Alpha Tool", asset_type="tool", owner="team-a")
    registry.register(key="model.beta", display_name="Beta Model", asset_type="model", owner="team-b")
    view = registry.governance_view()
    assert len(view) == 2
    keys = {item["key"] for item in view}
    assert keys == {"tool.alpha", "model.beta"}
    for row in view:
        assert "status" in row
        assert "asset_type" in row
        assert "owner" in row
        assert row["status"] == "active"


def test_governance_detail_drill_down():
    registry = CapabilityAssetRegistry()
    registry.register(
        key="tool.alpha",
        display_name="Alpha",
        asset_type="tool",
        owner="t",
        contract={"endpoint": "/alpha", "method": "POST"},
    )
    detail = registry.governance_detail("tool.alpha")
    assert detail is not None
    assert detail["key"] == "tool.alpha"
    assert detail["contract"] == {"endpoint": "/alpha", "method": "POST"}
    assert detail["status"] == "active"
    # unknown key -> None
    assert registry.governance_detail("nope") is None


def test_status_management_active_deprecated_offline():
    registry = CapabilityAssetRegistry()
    registry.register(key="tool.alpha", display_name="Alpha", asset_type="tool", owner="t")
    registry.register(key="tool.beta", display_name="Beta", asset_type="tool", owner="t")

    registry.set_status("tool.alpha", "deprecated", reason="superseded")
    assert registry.get_status("tool.alpha") == "deprecated"

    registry.set_status("tool.alpha", "offline", reason="retired")
    assert registry.get_status("tool.alpha") == "offline"

    # other asset unaffected
    assert registry.get_status("tool.beta") == "active"
    assert set(VALID_STATUSES) == {"active", "deprecated", "offline"}


def test_status_change_requires_approval():
    registry = CapabilityAssetRegistry()
    registry.register(key="tool.alpha", display_name="Alpha", asset_type="tool", owner="t")
    # T010 审批: require_approval without approver -> reject
    with pytest.raises(PermissionError):
        registry.set_status("tool.alpha", "offline", require_approval=True)
    # with approver -> succeeds
    registry.set_status("tool.alpha", "offline", approver="governance-admin", require_approval=True)
    assert registry.get_status("tool.alpha") == "offline"


def test_invalid_status_rejected():
    registry = CapabilityAssetRegistry()
    registry.register(key="tool.alpha", display_name="Alpha", asset_type="tool", owner="t")
    with pytest.raises(ValueError):
        registry.set_status("tool.alpha", "bogus")


def test_a2a_exposed_marking_for_agent_card():
    registry = CapabilityAssetRegistry()
    registry.register(key="tool.alpha", display_name="Alpha", asset_type="tool", owner="t")
    # 018 T011 / US2: the a2a_exposed marking is what 012 uses to build an AgentCard
    assert registry.is_a2a_exposed("tool.alpha") is False
    registry.mark_a2a_exposed("tool.alpha", exposed=True)
    assert registry.is_a2a_exposed("tool.alpha") is True
    registry.mark_a2a_exposed("tool.alpha", exposed=False)
    assert registry.is_a2a_exposed("tool.alpha") is False
    # unknown asset -> False, not an error
    assert registry.is_a2a_exposed("missing") is False


def test_discover_and_register_dedup():
    registry = CapabilityAssetRegistry()
    result = registry.discover_and_register(
        [
            {"key": "tool.x", "endpoint": "/x", "method": "GET", "owner": "t"},
            {"key": "tool.x", "endpoint": "/x", "method": "GET", "owner": "t"},  # dup
        ]
    )
    assert result["registered"] == ["tool.x"]
    assert result["duplicates"] == ["tool.x"]
    assert registry.is_a2a_exposed("tool.x") is False
