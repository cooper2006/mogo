"""023 T027 — /ready 端点测试。

验证依赖不可达时返回 503，可达时返回 200。

027 T038（MongoDB→PanWeiDB 切换）后：`_check_mongodb` 仅在
`effective_data_backend != "panweidb"` 时被调用；PanWeiDB 分支走
`_check_panweidb`（真实连接 `pg.ping_async`，无法用假 db monkeypatch）。
本测试按 `MOGO_DATA_BACKEND` 选支：mongo 后端保留原 patch 路径；
PanWeiDB 后端（容器/宿主）改 patch `_check_panweidb`。
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_PANWEIDB_BACKEND = os.environ.get("MOGO_DATA_BACKEND", "").strip().lower() in {"panweidb"}


def _fake_mongo(reachable: bool):
    async def _impl():
        return {"backend": "mongo", "reachable": reachable}

    return _impl


def _fake_redis(backend: str = "not_configured"):
    async def _impl():
        return {"redis": backend}

    return _impl


def _fake_pg(reachable: bool):
    async def _impl():
        return {"backend": "panweidb", "reachable": reachable}

    return _impl


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _patch_backend_probe(monkeypatch, reachable: bool, redis_backend: str = "not_configured"):
    """按当前 backend 选 patch：mongo 后端 patch `_check_mongodb`，PanWeiDB patch `_check_panweidb`。"""
    if _PANWEIDB_BACKEND:
        monkeypatch.setattr("app.observability.health._check_panweidb", _fake_pg(reachable))
    else:
        monkeypatch.setattr("app.observability.health._check_mongodb", _fake_mongo(reachable))
    monkeypatch.setattr("app.observability.health._check_redis", _fake_redis(redis_backend))


def test_ready_endpoint_returns_200_when_healthy(client, monkeypatch):
    """依赖可达时 /ready 返回 200。"""
    _patch_backend_probe(monkeypatch, reachable=True, redis_backend="not_configured")

    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reachable"] is True


def test_ready_endpoint_returns_503_when_mongo_down(client, monkeypatch):
    """后端（mongo/PanWeiDB）不可达时 /ready 返回 503。"""
    _patch_backend_probe(monkeypatch, reachable=False, redis_backend="not_configured")

    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_endpoint_returns_503_when_redis_down(client, monkeypatch):
    """Redis 不可达时 /ready 返回 503。"""
    _patch_backend_probe(monkeypatch, reachable=True, redis_backend="unreachable")

    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_endpoint_includes_backend_info(client, monkeypatch):
    """/ready 响应包含后端信息。"""
    _patch_backend_probe(monkeypatch, reachable=True, redis_backend="not_configured")

    resp = client.get("/ready")
    data = resp.json()
    expected_backend = "panweidb" if _PANWEIDB_BACKEND else "mongo"
    assert data["backend"] == expected_backend
    assert "redis" in data
