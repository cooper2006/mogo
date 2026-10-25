"""023 T027 — /ready 端点测试。

验证依赖不可达时返回 503，可达时返回 200。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_ready_endpoint_returns_200_when_healthy(client, monkeypatch):
    """依赖可达时 /ready 返回 200。"""
    async def _fake_mongo():
        return {"backend": "mongo", "reachable": True}

    async def _fake_redis():
        return {"redis": "not_configured"}

    monkeypatch.setattr("app.observability.health._check_mongodb", _fake_mongo)
    monkeypatch.setattr("app.observability.health._check_redis", _fake_redis)

    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reachable"] is True


def test_ready_endpoint_returns_503_when_mongo_down(client, monkeypatch):
    """MongoDB 不可达时 /ready 返回 503。"""
    async def _fake_mongo():
        return {"backend": "mongo", "reachable": False}

    async def _fake_redis():
        return {"redis": "not_configured"}

    monkeypatch.setattr("app.observability.health._check_mongodb", _fake_mongo)
    monkeypatch.setattr("app.observability.health._check_redis", _fake_redis)

    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_endpoint_returns_503_when_redis_down(client, monkeypatch):
    """Redis 不可达时 /ready 返回 503。"""
    async def _fake_mongo():
        return {"backend": "mongo", "reachable": True}

    async def _fake_redis():
        return {"redis": "unreachable"}

    monkeypatch.setattr("app.observability.health._check_mongodb", _fake_mongo)
    monkeypatch.setattr("app.observability.health._check_redis", _fake_redis)

    resp = client.get("/ready")
    assert resp.status_code == 503


def test_ready_endpoint_includes_backend_info(client, monkeypatch):
    """/ready 响应包含后端信息。"""
    async def _fake_mongo():
        return {"backend": "mongo", "reachable": True}

    async def _fake_redis():
        return {"redis": "not_configured"}

    monkeypatch.setattr("app.observability.health._check_mongodb", _fake_mongo)
    monkeypatch.setattr("app.observability.health._check_redis", _fake_redis)

    resp = client.get("/ready")
    data = resp.json()
    assert data["backend"] == "mongo"
    assert "redis" in data
