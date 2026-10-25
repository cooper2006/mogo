"""025 FR-9 (T019) — 内容协商中间件行为测试。

验证 `app/middleware/content_negotiation.py`：
- 不支持的 `Accept` → 406 + `Vary: Accept`
- `Accept: application/json` / `*/*` / `application/*+json` / `application/*` → 放行
- 无 `Accept` → 放行
- `Accept-Encoding: gzip` 时 JSON 响应压缩（`Content-Encoding: gzip` + `Vary: Accept-Encoding`）
- 未声明 gzip 时不压缩（仍带 `Vary: Accept-Encoding`）
- 非 JSON 响应即使声明 gzip 也不压缩
"""

from __future__ import annotations

import gzip
import json

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.middleware.content_negotiation import ContentNegotiationMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/data")
    async def data() -> dict[str, str]:
        return {"hello": "world"}

    @app.get("/text")
    async def text() -> PlainTextResponse:
        return PlainTextResponse("plain-text-body")

    app.add_middleware(ContentNegotiationMiddleware)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


class TestAccept:
    def test_no_accept_header_passes(self, client: TestClient) -> None:
        response = client.get("/data")
        assert response.status_code == 200
        assert response.json() == {"hello": "world"}

    def test_application_json_passes(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "application/json"})
        assert response.status_code == 200

    def test_wildcard_passes(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "*/*"})
        assert response.status_code == 200

    def test_vendor_json_passes(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "application/vnd.api+json"})
        assert response.status_code == 200

    def test_multiple_with_json_q(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "application/xml;q=1, application/json;q=0.5"})
        assert response.status_code == 200

    def test_unsupported_returns_406(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "text/html"})
        assert response.status_code == 406
        assert "vary" in {k.lower() for k in response.headers}
        assert response.headers.get("vary") == "Accept"
        assert "application/json" in response.headers.get("content-type", "")

    def test_q_zero_only_returns_406(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept": "application/json;q=0"})
        assert response.status_code == 406


class TestAcceptEncoding:
    def test_gzip_applied_when_declared(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept-encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in response.headers.get("vary", "")
        assert response.json() == {"hello": "world"}

    def test_raw_bytes_are_gzip(self) -> None:
        # 底层 ASGI 断言：中间件输出的原始 body 确实是 gzip 流（TestClient/httpx 会自动解压）
        messages = _raw_response(b"gzip")
        body = messages[-1]["body"]
        assert body[:2] == b"\x1f\x8b"
        assert json.loads(gzip.decompress(body)) == {"hello": "world"}

    def test_no_gzip_when_not_declared(self, client: TestClient) -> None:
        response = client.get("/data", headers={"accept-encoding": "identity"})
        assert response.status_code == 200
        assert "gzip" not in response.headers.get("content-encoding", "")
        assert response.json() == {"hello": "world"}

    def test_non_json_not_compressed_even_if_gzip(self, client: TestClient) -> None:
        response = client.get("/text", headers={"accept-encoding": "gzip"})
        assert response.status_code == 200
        assert "gzip" not in response.headers.get("content-encoding", "")
        assert response.text == "plain-text-body"


def _raw_response(accept_encoding: bytes) -> list[dict[str, object]]:
    """直接驱动中间件的底层 ASGI 调用，返回 send 收到的所有消息。"""

    import asyncio

    from app.middleware.content_negotiation import ContentNegotiationMiddleware

    async def inner_app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"hello":"world"}'})

    messages: list[dict[str, object]] = []

    async def sink(message: dict[str, object]) -> None:
        messages.append(message)

    scope: dict[str, object] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/x",
        "raw_path": b"/x",
        "query_string": b"",
        "headers": [(b"accept-encoding", accept_encoding)],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    middleware = ContentNegotiationMiddleware(inner_app)
    asyncio.run(middleware(scope, receive, sink))
    return messages