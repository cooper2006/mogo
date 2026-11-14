"""Regression: editing a self-registered / migrated user must not return 422.

历史 end_users 文档（自助注册账号，以及从 Mongo 迁到 PanWeiDB 的旧数据）可能
没有 mobile 字段、source 为 self_register、也没有岗位角色关联。旧的
UserUpdatePayload 把这些空值一律判为非法，管理端编辑保存时在请求体校验阶段
就返回 422，请求根本没走到数据库层。

放开校验后必须保持「留空 = 保持库中原值」的语义：不覆盖联系方式、不清除
self_register 账号的登录凭据、也不把空 roleIds 当成「清空全部角色」。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.api.routes import directory

USER_ID = "6af1225fbc3a012bdd8548f5a1b2c3d4"
DEPT_ID = "4beeb6e255694db49d15fe6d7d67121f"
TENANT = "org-50563e3a01257774635747c2"
LOGIN_NAME = "liujingyu@bonc.com.cn"

# 与远端 PanWeiDB 中真实的历史用户一致：无 mobile、self_register、无岗位角色。
LEGACY_PAYLOAD: dict[str, Any] = {
    "name": "秋意",
    "mobile": "",
    "email": LOGIN_NAME,
    "status": "active",
    "source": "self_register",
    "sourceUserId": "",
    "primaryDepartmentId": DEPT_ID,
    "departmentIds": [DEPT_ID],
    "loginName": LOGIN_NAME,
    "resetPassword": "",
    "primaryRoleId": "",
    "roleIds": [],
}


def test_legacy_self_register_payload_is_accepted() -> None:
    payload = directory.UserUpdatePayload(**LEGACY_PAYLOAD)
    assert payload.source == "self_register"
    assert payload.mobile == ""
    assert payload.primaryRoleId == ""
    assert payload.roleIds == []


def test_optional_fields_may_be_omitted() -> None:
    payload = directory.UserUpdatePayload(name="甲", primaryDepartmentId=DEPT_ID)
    assert payload.mobile == "" and payload.email == ""
    assert payload.status == "active" and payload.source == "local"
    assert payload.departmentIds == [] and payload.roleIds == []


@pytest.mark.parametrize(
    "override",
    [
        {"source": "ldap"},
        {"name": ""},
        {"primaryDepartmentId": ""},
        {"status": "pending"},
    ],
)
def test_invalid_values_are_still_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        directory.UserUpdatePayload(**{**LEGACY_PAYLOAD, **override})


class _Users:
    def __init__(self, existing: dict[str, Any]) -> None:
        self.existing = existing
        self.updates: list[dict[str, Any]] = []

    async def find_one(self, flt: dict[str, Any]) -> dict[str, Any]:
        return dict(self.existing)

    async def update_one(self, flt: dict[str, Any], ops: dict[str, Any]) -> None:
        self.updates.append(ops)


class _Db:
    def __init__(self, users: _Users) -> None:
        self.users = users

    def __getitem__(self, name: str) -> Any:
        return self.users


def test_update_user_preserves_legacy_data(monkeypatch: pytest.MonkeyPatch) -> None:
    users = _Users({
        "_id": USER_ID,
        "tenant_id": TENANT,
        "name": "秋意",
        "mobile": "13800000000",
        "email": LOGIN_NAME,
        "login_name": LOGIN_NAME,
        "password_hash": "stored-hash",
        "password_salt": "stored-salt",
        "primary_org_id": DEPT_ID,
    })
    monkeypatch.setattr(directory, "get_db", lambda: _Db(users))
    monkeypatch.setattr(directory, "_safe_oid", lambda value, detail: value)

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(directory, "_validate_departments", noop)
    monkeypatch.setattr(directory, "_upsert_user_relations", noop)
    monkeypatch.setattr(directory, "_write_audit", noop)

    class _MustNotConstruct:
        def __init__(self) -> None:
            raise AssertionError("空 roleIds 时不应构造 PositionRoleService")

    monkeypatch.setattr(directory, "PositionRoleService", _MustNotConstruct)

    admin = {"tenant_id": TENANT, "username": "admin"}
    result = asyncio.run(directory.update_user(
        USER_ID, directory.UserUpdatePayload(**LEGACY_PAYLOAD), admin,
    ))
    assert result == {"success": True}
    assert len(users.updates) == 1
    ops = users.updates[0]
    assert "mobile" not in ops["$set"], "留空不得覆盖库中已有的手机号"
    assert ops["$set"]["email"] == LOGIN_NAME
    assert "$unset" not in ops, "self_register 的 login_name / 密码不得被清除"
    assert ops["$set"]["login_name"] == LOGIN_NAME

    # 缺 email 的历史用户同样不能把空值写回覆盖原数据。
    without_email = {**LEGACY_PAYLOAD, "email": ""}
    asyncio.run(directory.update_user(
        USER_ID, directory.UserUpdatePayload(**without_email), admin,
    ))
    assert "email" not in users.updates[-1]["$set"]
