"""025 T009 — `POST /{resource_id}/delete` 资源化改名 + 兼容别名行为验证。

新路径 `POST /{resource_id}/deletion`（无动词段）；旧路径以
`include_in_schema=False, deprecated=True` 注册为 308 永久重定向别名。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MOD = "app.api.routes.personal_knowledge_internal"


@pytest.fixture
def client(monkeypatch):
    mod = importlib.import_module(MOD)
    monkeypatch.setattr(mod.settings, "backend_service_token", "test-token")
    app = FastAPI()
    app.include_router(mod.router, prefix="/internal/personal-knowledge")
    return TestClient(
        app, raise_server_exceptions=False, follow_redirects=False
    )


def test_legacy_delete_path_redirects_308_to_resource_path(client):
    """旧动词段路径返回 308，Location 指向新资源化路径。"""
    res = client.post(
        "/internal/personal-knowledge/resource-1/delete",
        json={"tenantId": "t", "ownerUserId": "u"},
        headers={"X-MOGO-Service-Token": "test-token"},
    )
    assert res.status_code == 308
    assert res.headers["location"].endswith(
        "/internal/personal-knowledge/resource-1/deletion"
    )


def test_legacy_path_still_requires_service_token(client):
    """别名端点不能绕过服务凭证鉴权。"""
    res = client.post(
        "/internal/personal-knowledge/resource-1/delete",
        json={"tenantId": "t", "ownerUserId": "u"},
        headers={"X-MOGO-Service-Token": "wrong"},
    )
    assert res.status_code == 401


def test_new_path_in_openapi_but_legacy_alias_hidden(client):
    """新资源化路径进入 OpenAPI schema；旧动词段路径被隐藏（include_in_schema=False）。"""
    paths = client.app.openapi()["paths"]
    assert (
        "/internal/personal-knowledge/{resource_id}/deletion" in paths
    ), "新路径必须出现在 OpenAPI schema 中"
    assert all(
        "/delete" not in key for key in paths
    ), "旧动词段路径不应出现在 OpenAPI schema 中"
