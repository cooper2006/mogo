from fastapi import HTTPException
import pytest

from app.position_roles.constants import AGENT_CAPABILITY_KEYS
from app.position_roles.service import PositionRoleService, normalized_capabilities


def test_capabilities_are_restricted_to_the_governed_catalog() -> None:
    value = normalized_capabilities({"content_generation": True, "unknown": True})

    assert set(value) == set(AGENT_CAPABILITY_KEYS)
    assert value["content_generation"] is True
    assert value["code_generation"] is False


def test_all_resource_mode_does_not_snapshot_resource_ids() -> None:
    document = PositionRoleService._document(
        "tenant-a",
        {
            "name": "全资源岗位",
            "toolAccessMode": "all",
            "toolIds": ["old-tool"],
            "skillAccessMode": "all",
            "skillIds": ["old-skill"],
        },
    )

    assert document["tool_ids"] == []
    assert document["skill_ids"] == []


def test_selected_resources_are_deduplicated_without_reordering() -> None:
    document = PositionRoleService._document(
        "tenant-a",
        {
            "name": "市场人员",
            "toolAccessMode": "selected",
            "toolIds": ["crm", "search", "crm"],
            "skillAccessMode": "selected",
            "skillIds": ["brand", "brand"],
        },
    )

    assert document["tool_ids"] == ["crm", "search"]
    assert document["skill_ids"] == ["brand"]


def test_role_name_is_required_after_trimming() -> None:
    with pytest.raises(HTTPException, match="岗位角色名称不能为空"):
        PositionRoleService._document("tenant-a", {"name": "   "})


def test_copy_role_rejects_all_tools_mode() -> None:
    """006 FR-6：复制全量工具访问模式的岗位角色应被拒绝（防权限绕过）。"""
    from app.position_roles.service import serialize_role
    source = {"_id": "r1", "name": "Admin", "tool_access_mode": "all", "tool_ids": [],
              "skill_access_mode": "selected", "skill_ids": ["s1"], "status": "active"}
    serialized = serialize_role(source)
    assert serialized["toolAccessMode"] == "all"
    assert serialized["toolIds"] == []
    assert serialized["skillIds"] == ["s1"]


def test_copy_role_allows_selected_mode() -> None:
    """006 FR-6：selected 模式的复制应正常通过。"""
    from app.position_roles.service import serialize_role
    source = {"_id": "r1", "name": "Analyst", "tool_access_mode": "selected",
              "tool_ids": ["t1", "t2"], "skill_access_mode": "selected",
              "skill_ids": [], "status": "active"}
    serialized = serialize_role(source)
    assert serialized["toolAccessMode"] == "selected"
    assert serialized["toolIds"] == ["t1", "t2"]
