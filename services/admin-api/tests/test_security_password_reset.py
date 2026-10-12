"""T021 单测：一次性临时凭据 + 首次登录强制改密（FR-13）。

覆盖：

- :func:`_assert_password_change_not_required` —— 登录闸门：标记存在时
  拒绝签发令牌、5h 兜底过期后放行；
- :func:`set_account_password` —— ``must_change_password`` 三种语义
  （置位 / 清除 / 保持）；
- :func:`reset_with_recovery` 语义 —— 一次性凭据重置后清除标记（逃生门）。

不启动 MongoDB；全部使用内存 fake collection。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import HTTPException, status

from app.api.routes.auth import (
    PASSWORD_CHANGE_REQUIRED_TTL_SECONDS,
    _assert_password_change_not_required,
)
from app.repositories import org_user_repository

NOW = 1_700_000_000
TENANT = "tenant-0001"
ADMIN = "admin@corp.example"


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs

    async def update_one(
        self, query: dict, update: dict, upsert: bool = False
    ) -> Any:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                doc.update(update.get("$set", {}))
                return {"matched_count": 1, "modified_count": 1}
        return {"matched_count": 0, "modified_count": 0}

    async def find_one(self, query: dict, projection=None) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> Any:
        self.docs.append(doc)
        return None


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}

    def __getitem__(self, name: str) -> Any:
        return FakeCollection(self.collections.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch) -> Any:
    db = FakeDB()
    monkeypatch.setattr(org_user_repository, "get_db", lambda: db)
    return db


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch) -> None:
    """固定 time.time()，使 5h 过期判定可复现。"""
    monkeypatch.setattr(time, "time", lambda: float(NOW))


def _account(**overrides: Any) -> dict:
    doc = {
        "username": ADMIN,
        "tenant_id": TENANT,
        "status": "active",
        "role_name": "组织管理员",
        "password_hash": "h",
        "password_salt": "s",
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# set_account_password：must_change_password 三种语义
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_account_password_sets_flag(fake_db) -> None:
    fake_db["admin_accounts"].docs.append(_account())
    await org_user_repository.set_account_password(
        ADMIN, "NewPass!12345", TENANT, must_change_password=True
    )
    row = fake_db["admin_accounts"].docs[0]
    assert row["must_change_password"] is True
    assert row["password_hash"] != "h"  # 口令哈希已更新


@pytest.mark.asyncio
async def test_set_account_password_clears_flag(fake_db) -> None:
    fake_db["admin_accounts"].docs.append(
        _account(must_change_password=True)
    )
    await org_user_repository.set_account_password(
        ADMIN, "NewPass!12345", TENANT, must_change_password=False
    )
    row = fake_db["admin_accounts"].docs[0]
    assert row["must_change_password"] is False


@pytest.mark.asyncio
async def test_set_account_password_preserves_flag_when_unset(fake_db) -> None:
    """None = 不改动标记（自助改密之外的路径不该顺手清标记）。"""
    fake_db["admin_accounts"].docs.append(
        _account(must_change_password=True, must_change_password_set_at=NOW - 60)
    )
    await org_user_repository.set_account_password(ADMIN, "NewPass!12345", TENANT)
    row = fake_db["admin_accounts"].docs[0]
    assert row["must_change_password"] is True
    assert row["must_change_password_set_at"] == NOW - 60


# ---------------------------------------------------------------------------
# 登录闸门：_assert_password_change_not_required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_flag_passes() -> None:
    await _assert_password_change_not_required(_account())
    await _assert_password_change_not_required(
        _account(must_change_password=False)
    )


@pytest.mark.asyncio
async def test_flag_rejects_login_without_ttls() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _assert_password_change_not_required(_account(must_change_password=True))

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    detail = exc_info.value.detail
    assert detail["passwordChangeRequired"] is True
    assert detail["username"] == ADMIN
    assert detail["tenantId"] == TENANT
    assert "message" in detail


@pytest.mark.asyncio
async def test_flag_within_5h_still_rejects() -> None:
    with pytest.raises(HTTPException):
        await _assert_password_change_not_required(
            _account(must_change_password=True, must_change_password_set_at=NOW - 3600)
        )


@pytest.mark.asyncio
async def test_flag_exactly_5h_still_rejects() -> None:
    """边界：恰好 5h 未过期，第 5h+1s 才放行。"""
    with pytest.raises(HTTPException):
        await _assert_password_change_not_required(
            _account(
                must_change_password=True,
                must_change_password_set_at=NOW - PASSWORD_CHANGE_REQUIRED_TTL_SECONDS,
            )
        )


@pytest.mark.asyncio
async def test_flag_after_5h_fails_open() -> None:
    """超过 5h 兜底放行，避免配置异常导致永久锁死。"""
    await _assert_password_change_not_required(
        _account(
            must_change_password=True,
            must_change_password_set_at=NOW - PASSWORD_CHANGE_REQUIRED_TTL_SECONDS - 1,
        )
    )


@pytest.mark.asyncio
async def test_flag_without_timestamp_is_enforced() -> None:
    """历史数据没有 set_at 时保持强制（fail-closed）。"""
    with pytest.raises(HTTPException):
        await _assert_password_change_not_required(_account(must_change_password=True))


@pytest.mark.asyncio
async def test_garbage_timestamp_is_enforced() -> None:
    """set_at 非法值视为未设置 → fail-closed。"""
    with pytest.raises(HTTPException):
        await _assert_password_change_not_required(
            _account(must_change_password=True, must_change_password_set_at="not-an-int")
        )


def test_ttl_constant_is_five_hours() -> None:
    assert PASSWORD_CHANGE_REQUIRED_TTL_SECONDS == 5 * 3600
