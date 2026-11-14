"""023 T026 — 日志级别切换测试。

验证 /admin/log-level POST 端点切换生效。
"""
from __future__ import annotations

import logging

import pytest
import structlog
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_log_level_endpoint_switches(client):
    """POST /admin/log-level 切换日志级别。"""
    resp = client.post("/admin/log-level", json={"level": "debug"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == "DEBUG"

    # 切换后 structlog logger 级别应更新
    log = structlog.get_logger("test_log_level_switch")
    log.debug("debug message after switch")

    # 恢复
    resp = client.post("/admin/log-level", json={"level": "info"})
    assert resp.status_code == 200


def test_log_level_endpoint_rejects_invalid(client):
    """无效日志级别返回 400。"""
    resp = client.post("/admin/log-level", json={"level": "not_a_level"})
    assert resp.status_code == 400
    assert "invalid log level" in resp.json()["detail"]


def test_log_level_endpoint_requires_body(client):
    """缺少 body 返回 422。"""
    resp = client.post("/admin/log-level")
    assert resp.status_code == 422
