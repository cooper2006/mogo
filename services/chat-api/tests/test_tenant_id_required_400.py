"""058 T021/T022 — tenant_id 缺省的 HTTP 契约：必须返回 400 而非 200/500。

``billing.py`` 抛出的 ``TenantIdRequiredError`` 已在 ``error_handler.py`` 注册为
400 处理器；本测试用 Starlette TestClient 验证端到端 HTTP 形状。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.billing import TenantIdRequiredError
from app.core.error_handler import register_error_handlers


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/needs-tenant")
    async def _needs_tenant():
        raise TenantIdRequiredError("tenant_id is required")

    register_error_handlers(app, is_prod=False)
    return app


def test_tenant_id_required_returns_400() -> None:
    client = TestClient(_make_app())
    resp = client.get("/needs-tenant")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "tenant_id_required"
    assert body["http_status"] == 400
    assert "tenant_id" in body["message"].lower()


def test_tenant_id_required_not_500() -> None:
    """回归：不得落入通用 Exception handler 返回 500。"""
    client = TestClient(_make_app())
    resp = client.get("/needs-tenant")
    assert resp.status_code != 500


def test_tenant_id_required_error_code_attribute() -> None:
    err = TenantIdRequiredError()
    assert err.code == "tenant_id_required"
    assert isinstance(err, ValueError)