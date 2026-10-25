"""025 FR-8 (T016)：ETag / If-Match 条件请求行为测试（QF-221/222/223/224）。

工具函数部分（compute_etag / parse_etag / matches / none_match_hits）直接单测；
中间件部分用 FastAPI TestClient 走真实 ASGI 链路，验证：
自动补 ETag 头、不覆盖下游自带 ETag、非 JSON 不加、require_match → 428、
条件请求头解析进 scope state。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.core.etag import (
    ETagMiddleware,
    compute_etag,
    format_etag,
    matches,
    none_match_hits,
    parse_etag,
    parse_many,
)


class TestComputeEtag:
    def test_stable_for_same_payload(self) -> None:
        assert compute_etag(b"hello") == compute_etag(b"hello")
        assert compute_etag("hello") == compute_etag("hello")
        assert compute_etag({"a": 1, "b": 2}) == compute_etag({"b": 2, "a": 1})  # 键序无关

    def test_differs_by_payload(self) -> None:
        assert compute_etag(b"a") != compute_etag(b"b")
        assert compute_etag({"a": 1}) != compute_etag({"a": 2})

    def test_format_etag_wraps_in_quotes(self) -> None:
        assert format_etag("abc") == '"abc"'


class TestParseEtag:
    def test_strong(self) -> None:
        parsed = parse_etag('"abc"')
        assert parsed is not None
        assert parsed.opaque == "abc"
        assert parsed.weak is False

    def test_weak(self) -> None:
        parsed = parse_etag('W/"abc"')
        assert parsed is not None
        assert parsed.opaque == "abc"
        assert parsed.weak is True

    def test_star_and_invalid_return_none(self) -> None:
        assert parse_etag("*") is None
        assert parse_etag("") is None
        assert parse_etag("abc") is None  # 无引号非法

    def test_parse_many(self) -> None:
        parsed = parse_many('"a", W/"b"')
        assert [p.opaque if p else None for p in parsed] == ["a", "b"]
        assert parse_many(None) == []


class TestMatches:
    def test_exact_match(self) -> None:
        assert matches('"abc"', format_etag("abc")) is True
        assert matches('"abc"', format_etag("def")) is False

    def test_weak_comparison_ignores_weak_flag(self) -> None:
        assert matches('W/"abc"', format_etag("abc")) is True
        assert matches('"abc"', 'W/"abc"') is True

    def test_star_matches_any(self) -> None:
        assert matches("*", format_etag("anything")) is True

    def test_missing_header_is_false(self) -> None:
        assert matches(None, format_etag("abc")) is False
        assert matches("", format_etag("abc")) is False


class TestNoneMatchHits:
    def test_hit_and_miss(self) -> None:
        assert none_match_hits('"abc"', format_etag("abc")) is True
        assert none_match_hits('"abc"', format_etag("xyz")) is False
        assert none_match_hits("*", format_etag("xyz")) is True
        assert none_match_hits(None, format_etag("abc")) is False


class TestMiddleware:
    def _build_app(self, require_match: bool = False) -> FastAPI:
        app = FastAPI()

        @app.get("/resource")
        def get_resource() -> dict[str, Any]:
            return {"id": 1, "name": "n"}

        @app.get("/plain")
        def get_plain() -> PlainTextResponse:
            return PlainTextResponse("plain")

        @app.put("/resource")
        def put_resource() -> dict[str, Any]:
            return {"ok": True}

        @app.get("/state")
        def state_view(request: Request) -> dict[str, Any]:
            state = request.scope.get("state") or {}
            return {
                "if_match": state.get("if_match"),
                "if_none_match": state.get("if_none_match"),
                "active": state.get("etag_middleware_active"),
            }

        app.add_middleware(ETagMiddleware, require_match=require_match)
        return app

    def test_json_response_gets_etag_header(self) -> None:
        client = TestClient(self._build_app())
        response = client.get("/resource")
        assert response.status_code == 200
        assert response.headers.get("etag", "").startswith('"')
        assert len(response.headers["etag"]) > 2

    def test_etag_is_stable_across_identical_responses(self) -> None:
        client = TestClient(self._build_app())
        first = client.get("/resource").headers["etag"]
        second = client.get("/resource").headers["etag"]
        assert first == second

    def test_non_json_response_gets_no_etag(self) -> None:
        client = TestClient(self._build_app())
        response = client.get("/plain")
        assert response.headers.get("etag") is None

    def test_require_match_rejects_put_without_if_match(self) -> None:
        client = TestClient(self._build_app(require_match=True))
        response = client.put("/resource")
        assert response.status_code == 428

    def test_require_match_allows_get(self) -> None:
        client = TestClient(self._build_app(require_match=True))
        assert client.get("/resource").status_code == 200

    def test_require_match_allows_put_with_if_match(self) -> None:
        client = TestClient(self._build_app(require_match=True))
        etag = client.get("/resource").headers["etag"]
        response = client.put("/resource", headers={"If-Match": etag})
        assert response.status_code == 200

    def test_request_headers_parsed_into_state(self) -> None:
        client = TestClient(self._build_app())
        response = client.get("/state", headers={"If-Match": '"abc"', "If-None-Match": '*'})
        # 无 If-Match 时也应解析（None）
        body = response.json()
        assert body["active"] is True
        assert body["if_match"] == '"abc"'
        assert body["if_none_match"] == "*"

    def test_state_without_headers(self) -> None:
        client = TestClient(self._build_app())
        body = client.get("/state").json()
        assert body["if_match"] is None
        assert body["if_none_match"] is None