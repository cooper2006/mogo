"""T033/T034 单测：CORS 显式白名单（022 FR-16 / QF-640）。

覆盖 :mod:`app.middleware.cors`：

- ``parse_origins``：空值 / 逗号分隔 / 去空白去重 / 通配符拒绝；
- ``build_cors_middleware_kwargs``：方法 / 头部白名单显式化，``*`` 被剔除；
- 应用接入点：``app.main`` 不再传 ``allow_methods=["*"]``。

不依赖网络，全部内存构造。
"""

from __future__ import annotations

import logging

import pytest

from app.middleware.cors import (
    DEFAULT_ALLOW_HEADERS,
    DEFAULT_ALLOW_METHODS,
    build_cors_middleware_kwargs,
    parse_origins,
)


# ---------------------------------------------------------------------------
# parse_origins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", []),
        (",", []),
        ("   ", []),
        ("http://a", ["http://a"]),
        ("http://a,http://b", ["http://a", "http://b"]),
        (" http://a , http://b ,", ["http://a", "http://b"]),
        ("http://a,http://a", ["http://a"]),  # 去重
    ],
)
def test_parse_origins_normalises(value, expected) -> None:
    assert parse_origins(value) == expected


def test_parse_origins_accepts_list_input() -> None:
    """pydantic ``list[str]`` 字段可直接传入，不需要字符串再切分。"""
    assert parse_origins(["http://a", "http://b"]) == ["http://a", "http://b"]


@pytest.mark.parametrize("value", ["*", " * ", "http://a/*", "*.example.com"])
def test_parse_origins_rejects_wildcard(value: str, caplog: pytest.LogCaptureFixture) -> None:
    """``*`` 在 allow_credentials=True 下无法被 Starlette 正确反射，必须拒绝。"""
    with caplog.at_level(logging.WARNING):
        assert parse_origins(value) == []
    assert any("wildcard" in r.getMessage().lower() for r in caplog.records)


def test_parse_origins_rejects_wildcard_but_keeps_valid_origin() -> None:
    """配置里混了通配与合法来源时，只丢通配、保留合法项。"""
    assert parse_origins("*,http://a") == ["http://a"]


def test_parse_origins_rejects_glob_suffix() -> None:
    """``*.example.com`` 这类子域通配同样拒绝（避免部署方误以为生效）。"""
    assert parse_origins("*.example.com") == []


def test_parse_origins_strips_trailing_slash() -> None:
    """origin 比较要求精确匹配，尾部斜杠会让 Starlette 匹配失败。"""
    assert parse_origins("http://a/") == ["http://a"]


# ---------------------------------------------------------------------------
# build_cors_middleware_kwargs
# ---------------------------------------------------------------------------


def test_kwargs_reject_wildcard_methods_and_headers() -> None:
    """入口必须拦掉 '*'，否则 Starlette 会反射任意方法/头部。"""
    kwargs = build_cors_middleware_kwargs(
        "http://a",
        allow_methods=["*", "GET", "POST"],
        allow_headers=["*", "Authorization"],
    )
    assert "*" not in kwargs["allow_methods"]
    assert "*" not in kwargs["allow_headers"]
    assert list(kwargs["allow_methods"]) == ["GET", "POST"]
    assert list(kwargs["allow_headers"]) == ["Authorization"]


def test_kwargs_method_names_are_uppercased() -> None:
    """方法名大小写归一，避免 ['get'] 之类配置被 Starlette 忽略。"""
    kwargs = build_cors_middleware_kwargs("http://a", allow_methods=["get", "post"])
    assert kwargs["allow_methods"] == ["GET", "POST"]


def test_kwargs_preserve_header_case() -> None:
    """HTTP 头部名大小写不敏感但习惯保留，不做归一。"""
    kwargs = build_cors_middleware_kwargs(
        "http://a", allow_headers=["authorization", "Content-Type"]
    )
    assert kwargs["allow_headers"] == ["authorization", "Content-Type"]


def test_default_methods_are_explicit_whitelist() -> None:
    assert "*" not in DEFAULT_ALLOW_METHODS
    assert "OPTIONS" in DEFAULT_ALLOW_METHODS  # 预检方法必须显式列出
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert method in DEFAULT_ALLOW_METHODS


def test_default_headers_cover_actual_headers() -> None:
    assert "*" not in DEFAULT_ALLOW_HEADERS
    # 服务端真正读取的请求头必须都在白名单里，否则预检会被拒。
    for header in ("Authorization", "Content-Type", "X-MOGO-Service-Token", "X-Request-ID"):
        assert header in DEFAULT_ALLOW_HEADERS


def test_kwargs_empty_origins_does_not_raise() -> None:
    """空来源是合法状态（服务端不接受任何跨域请求），不能抛异常。"""
    kwargs = build_cors_middleware_kwargs("")
    assert kwargs["allow_origins"] == []
    assert kwargs["allow_credentials"] is True


def test_kwargs_empty_origins_logs_hint(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        build_cors_middleware_kwargs("")
    assert any("CORS_ORIGINS is empty" in r.getMessage() for r in caplog.records)


def test_kwargs_preserves_credentials_flag() -> None:
    kwargs = build_cors_middleware_kwargs("http://a", allow_credentials=False)
    assert kwargs["allow_credentials"] is False


# ---------------------------------------------------------------------------
# 集成：真实中间件行为（preflight 响应）
# ---------------------------------------------------------------------------


def _app_with_cors(origins) -> "FastAPI":
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI()
    app.add_middleware(CORSMiddleware, **build_cors_middleware_kwargs(origins))

    @app.get("/probe")
    async def _probe() -> dict[str, str]:
        return {"ok": "1"}

    return app


def test_preflight_is_denied_when_origin_not_allowlisted() -> None:
    """未登记的 Origin 不允许跨域读响应。"""
    from starlette.testclient import TestClient

    client = TestClient(_app_with_cors("http://allowed.example"))
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400  # Starlette 对不允许的 origin 返回 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_allowlists_only_whitelisted_method() -> None:
    """预检只回显白名单内提出的方法，而不是原样反射任意方法。"""
    from starlette.testclient import TestClient

    client = TestClient(_app_with_cors("http://allowed.example"))
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-methods"]
    assert "GET" in allowed
    # 请求里没提的任意方法不能凭空被反射
    assert "FOO" not in allowed


def test_preflight_headers_are_whitelisted() -> None:
    """Access-Control-Allow-Headers 只包含白名单头部。"""
    from starlette.testclient import TestClient

    client = TestClient(_app_with_cors("http://allowed.example"))
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "content-type" in allowed


def test_preflight_rejects_unlisted_requested_header() -> None:
    """客户端提出白名单外的自定义头时预检直接失败（fail-closed），
    而不是像 ``allow_headers=['*']`` 那样被原样反射回响应。
    """
    from starlette.testclient import TestClient

    client = TestClient(_app_with_cors("http://allowed.example"))
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Custom-Attack",
        },
    )
    # Starlette 对"请求的头部不在白名单内"的预检返回 400；
    # 即使响应里带 allow-headers 头，也绝不会出现客户端提出的攻击头。
    assert response.status_code == 400
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "x-custom-attack" not in allowed


def test_wildcard_origin_is_not_reflected() -> None:
    """配置里写了 '*' 也必须被入口拦掉，而不是被 Starlette 反射成通配。"""
    from starlette.testclient import TestClient

    client = TestClient(_app_with_cors("*"))
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://anything.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
