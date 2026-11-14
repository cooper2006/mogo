"""058 T022 — 缺省租户 fail-closed 回归。

T021 删除了 ``if tenant_id in ("default", ""): return`` 的短路放行分支，
本用例守住两个入口：缺少 tenant_id 时必须抛带稳定 code 的异常，且**不得**
触碰数据库（fail-closed 要在任何 I/O 之前生效）。
"""
from __future__ import annotations

import pytest

from app.core import billing


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", ["", "default", "   "])
async def test_check_quota_before_request_rejects_missing_tenant(tenant_id, monkeypatch):
    def _must_not_touch_db(*args, **kwargs):
        raise AssertionError("fail-closed 应在任何 DB 访问之前生效")

    monkeypatch.setattr(billing, "get_db", _must_not_touch_db)
    with pytest.raises(billing.TenantIdRequiredError) as exc:
        await billing.check_quota_before_request(tenant_id, {"tenant_id": "default"})
    assert exc.value.code == "tenant_id_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", ["", "default"])
async def test_deduct_points_after_request_rejects_missing_tenant(tenant_id, monkeypatch):
    def _must_not_touch_db(*args, **kwargs):
        raise AssertionError("fail-closed 应在任何 DB 访问之前生效")

    monkeypatch.setattr(billing, "get_db", _must_not_touch_db)
    with pytest.raises(billing.TenantIdRequiredError) as exc:
        await billing.deduct_points_after_request(tenant_id, 100)
    assert exc.value.code == "tenant_id_required"


@pytest.mark.asyncio
async def test_valid_tenant_proceeds_to_db(monkeypatch):
    """有效 tenant_id 不应被误拦；用假 DB 走完共享模型额度检查路径。"""

    class _Cursor:
        async def to_list(self, length=None):
            return []

    class _Coll:
        async def find_one(self, query):
            return {"tenant_id": "real-tenant", "used_points": 0, "total_points": 1000,
                    "is_own_model": False, "tier": "free"}

        def find(self, query):
            return _Cursor()

        async def insert_one(self, doc):
            return None

    class _Db:
        def __getitem__(self, name):
            return _Coll()

    monkeypatch.setattr(billing, "get_db", lambda: _Db())
    # 不抛异常即通过
    await billing.check_quota_before_request("real-tenant", {"tenant_id": "default"})
