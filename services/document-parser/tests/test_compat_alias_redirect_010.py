"""025 T010 — `POST /vectors/documents/delete` 资源化改名 + 兼容别名行为验证。

新路径 `POST /vectors/documents/deletion`（无动词段）；旧路径以
`include_in_schema=False, deprecated=True` 注册为 308 永久重定向别名。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MOD = "app.api.routes.vector_maintenance"


@pytest.fixture
def client():
    from app.core.security import verify_service_token

    mod = importlib.import_module(MOD)
    app = FastAPI()
    app.include_router(mod.router, tags=["vector-maintenance"])
    # 别名端点复用 `Depends(verify_service_token)`，测试里放行鉴权
    app.dependency_overrides[verify_service_token] = lambda: None
    return TestClient(
        app, raise_server_exceptions=False, follow_redirects=False
    )


def test_legacy_delete_path_redirects_308(client):
    """旧动词段路径返回 308，Location 指向新资源化路径。"""
    res = client.post(
        "/vectors/documents/delete",
        json={"tenantId": "t", "documentId": "d-1", "config": {}},
        headers={"X-MOGO-Service-Token": "test-token"},
    )
    assert res.status_code == 308
    assert res.headers["location"].endswith("/vectors/documents/deletion")


def test_new_path_in_openapi_but_legacy_alias_hidden(client):
    """新路径进入 OpenAPI schema；旧动词段路径被隐藏。"""
    paths = client.app.openapi()["paths"]
    assert "/vectors/documents/deletion" in paths
    assert all(
        "/delete" not in key for key in paths
    ), "旧动词段路径不应出现在 OpenAPI schema 中"
