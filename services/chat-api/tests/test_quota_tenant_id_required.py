"""058 T021/T022 — tenant_id 缺省 fail-closed 回归。

不带 / 空白 / ``"default"`` 租户的请求必须在任何 DB 访问前被拒绝
（``TenantIdRequiredError``，``code=tenant_id_required``）。
"""

from __future__ import annotations

import pytest

from app.core.billing import (
    TenantIdRequiredError,
    check_quota_before_request,
    deduct_points_after_request,
)


@pytest.mark.asyncio
async def test_check_quota_rejects_empty_tenant() -> None:
    with pytest.raises(TenantIdRequiredError):
        await check_quota_before_request("", {})


@pytest.mark.asyncio
async def test_check_quota_rejects_default_tenant() -> None:
    with pytest.raises(TenantIdRequiredError):
        await check_quota_before_request("default", {})


@pytest.mark.asyncio
async def test_check_quota_rejects_whitespace_tenant() -> None:
    with pytest.raises(TenantIdRequiredError):
        await check_quota_before_request("   ", {})


@pytest.mark.asyncio
async def test_deduct_rejects_empty_tenant() -> None:
    with pytest.raises(TenantIdRequiredError):
        await deduct_points_after_request("", 10)


def test_tenant_id_required_error_code() -> None:
    err = TenantIdRequiredError()
    assert err.code == "tenant_id_required"
