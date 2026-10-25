"""025 FR-5 (T013) — 载荷限制中间件行为测试。

验证 `app/middleware/payload_limit.py`：
- 请求体超过 `max_bytes` → 413
- JSON 嵌套深度 / 数组长度 / 字符串长度超限 → 422
- 合法请求正常放行，且下游仍能读到完整 body
- 非 JSON 请求只做字节数限制
- 按路径前缀的 overrides 生效
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config.payload_limits import PayloadLimits
from app.middleware.payload_limit import PayloadLimitMiddleware

# 测试用的小限制，便于构造超限载荷
LIMITS = PayloadLimits(
    max_bytes=100,
    max_depth=3,
    max_array_length=2,
    max_string_length=10,
    overrides={"/internal": {"max_bytes": 500}},
)


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, Any]:
        body = await request.body()
        return {"length": len(body), "body": body.decode("utf-8", errors="replace")}

    @app.post("/internal/echo")
    async def internal_echo(request: Request) -> dict[str, Any]:
        return {"length": len(await request.body())}

    app.add_middleware(PayloadLimitMiddleware, limits=LIMITS)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


def _post(client: TestClient, path: str, body: Any, content_type: str = "application/json"):
    return client.post(path, content=body, headers={"content-type": content_type})


class TestSizeLimit:
    def test_over_max_bytes_returns_413(self, client: TestClient) -> None:
        response = _post(client, "/echo", b"x" * 101)
        assert response.status_code == 413
        assert "超过大小限制" in response.json()["detail"]

    def test_non_json_over_max_bytes_still_413(self, client: TestClient) -> None:
        response = _post(client, "/echo", b"x" * 101, content_type="text/plain")
        assert response.status_code == 413


class TestShapeLimit:
    def test_nesting_too_deep_422(self, client: TestClient) -> None:
        # depth: {"a": {"b": {"c": {"d": 1}}}} → 5 > 3
        response = _post(client, "/echo", b'{"a":{"b":{"c":{"d":1}}}}')
        assert response.status_code == 422
        assert "嵌套深度" in response.json()["detail"]

    def test_array_too_long_422(self, client: TestClient) -> None:
        response = _post(client, "/echo", b'[1,2,3]')
        assert response.status_code == 422
        assert "数组元素数" in response.json()["detail"]

    def test_string_too_long_422(self, client: TestClient) -> None:
        response = _post(client, "/echo", b'{"name":"abcdefghijk"}')
        assert response.status_code == 422
        assert "字符串长度" in response.json()["detail"]

    def test_within_depth_and_size_ok(self, client: TestClient) -> None:
        response = _post(client, "/echo", b'{"a":{"b":1}}')
        assert response.status_code == 200
        assert response.json()["length"] == len(b'{"a":{"b":1}}')


class TestPassThrough:
    def test_non_json_passes_with_body(self, client: TestClient) -> None:
        response = _post(client, "/echo", b"hello world", content_type="text/plain")
        assert response.status_code == 200
        assert response.json()["body"] == "hello world"

    def test_get_without_body_passes(self, client: TestClient) -> None:
        response = client.get("/echo")
        assert response.status_code in (200, 405)


class TestOverrides:
    def test_internal_prefix_relaxed(self, client: TestClient) -> None:
        # /internal 覆盖 max_bytes=500，故 300 字节应放行
        response = _post(client, "/internal/echo", b"y" * 300)
        assert response.status_code == 200
        assert response.json()["length"] == 300