"""025 T045 回归：旧路径 301 必须保留网关反代前缀（2026-10-27 修）。

线上症状：admin-web 请求 ``/admin-api/api/setup/status``，网关剥掉前缀后
admin-api 收到 ``/api/setup/status``，中间件 301 到 ``/api/v1/setup/status``
（丢了 ``/admin-api``），浏览器跟随后落到网关的 ``location /api/``（chat-api）
→ **404**，请求串到了另一个服务。

修复口径：网关用 ``X-Forwarded-Prefix`` 告知原始前缀，Location 必须带回去；
前缀来自请求头，必须校验，避免被伪造成开放重定向。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.legacy_api_redirect import LegacyApiRedirectMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(LegacyApiRedirectMiddleware)

    @app.get("/api/v1/setup/status")
    def _status() -> dict:
        return {"ok": True}

    @app.post("/api/v1/sessions")
    def _create() -> dict:
        return {"ok": True}

    return TestClient(app, follow_redirects=False)


def test_legacy_path_redirects_to_v1() -> None:
    """无反代前缀（直连服务）时保持原语义。"""
    res = _client().get("/api/setup/status")
    assert res.status_code == 301
    assert res.headers["location"] == "/api/v1/setup/status"


def test_redirect_keeps_forwarded_prefix() -> None:
    res = _client().get("/api/setup/status", headers={"X-Forwarded-Prefix": "/admin-api"})
    assert res.status_code == 301
    assert res.headers["location"] == "/admin-api/api/v1/setup/status"


def test_write_method_uses_308_and_keeps_prefix() -> None:
    res = _client().post("/api/sessions", headers={"X-Forwarded-Prefix": "/admin-api"})
    assert res.status_code == 308
    assert res.headers["location"] == "/admin-api/api/v1/sessions"


def test_query_string_is_appended_after_prefixed_path() -> None:
    res = _client().get("/api/sessions?limit=10", headers={"X-Forwarded-Prefix": "/askai-api"})
    assert res.headers["location"] == "/askai-api/api/v1/sessions?limit=10"


@pytest.mark.parametrize(
    "bad_prefix",
    ["//evil.example", "/a/../b", "http://evil.example", "admin-api", "/admin-api?x=1", ""],
)
def test_unsafe_or_malformed_prefix_is_ignored(bad_prefix: str) -> None:
    res = _client().get("/api/setup/status", headers={"X-Forwarded-Prefix": bad_prefix})
    assert res.headers["location"] == "/api/v1/setup/status"


def test_v1_path_is_never_redirected() -> None:
    res = _client().get("/api/v1/setup/status")
    assert res.status_code == 200


@pytest.mark.parametrize("method,expected_status", [("get", 301), ("post", 308)])
def test_redirect_must_not_be_cached_by_browser(method: str, expected_status: int) -> None:
    """301 是永久重定向，发错一次浏览器会长期记住（2026-10-27 事故）。

    迁移期目标路径还可能变，必须 no-store，让每次旧路径请求都回到服务端判定。
    """
    res = getattr(_client(), method)("/api/setup/status")
    assert res.status_code == expected_status
    assert res.headers["cache-control"] == "no-store"
