"""026 T042/T043 — 限流与背压中间件测试（FR-28）。

用 FastAPI TestClient 验证：超限返回 429 + Retry-After；队列满返回 503；
放行路径正常；错误响应为 RFC 9457 problem+json。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.perf_guards import (
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_DEPTH,
    DEFAULT_RATE_LIMIT_RPS,
    BackpressureMiddleware,
    RateLimitMiddleware,
)


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


class TestRateLimitMiddleware:
    def test_under_limit_ok(self) -> None:
        app = _make_app()
        app.add_middleware(RateLimitMiddleware, rps=1000.0, burst=1000)
        client = TestClient(app)
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_exceed_rate_returns_429_with_retry_after(self) -> None:
        # 固定 key_func，避免 TestClient host 变化
        app = _make_app()
        app.add_middleware(RateLimitMiddleware, rps=0.0001, burst=1, max_concurrent=10,
                           key_func=lambda req: "fixed")
        client = TestClient(app)
        assert client.get("/ping").status_code == 200  # 消耗唯一令牌
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] >= "1"
        body = resp.json()
        assert body["status"] == 429
        assert "title" in body and "detail" in body

    def test_concurrency_rejection(self) -> None:
        # 用显式 limiter 占满并发槽 → 中间件直接 429
        from app.common.dependency_guard import RateLimiter

        limiter = RateLimiter(qps=1000.0, burst=1000, max_concurrent=1)
        app = _make_app()
        app.add_middleware(RateLimitMiddleware, limiter=limiter, key_func=lambda req: "fixed")
        assert limiter.acquire("fixed").allowed is True
        client = TestClient(app)
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        limiter.release("fixed")

    def test_qps_rejection_when_tokens_exhausted(self) -> None:
        app = _make_app()
        # 用极低 qps 但足够 burst，让令牌快速耗尽
        app.add_middleware(RateLimitMiddleware, rps=0.0001, burst=1, max_concurrent=10)
        client = TestClient(app)
        assert client.get("/ping").status_code == 200  # 消耗唯一令牌
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_default_constants(self) -> None:
        assert DEFAULT_RATE_LIMIT_RPS == 1000.0
        assert DEFAULT_MAX_CONCURRENT == 500
        assert DEFAULT_MAX_DEPTH == 1000


class TestBackpressureMiddleware:
    def test_under_depth_ok(self) -> None:
        app = _make_app()
        app.add_middleware(BackpressureMiddleware, max_depth=10)
        client = TestClient(app)
        resp = client.get("/ping")
        assert resp.status_code == 200

    def test_queue_full_returns_503(self) -> None:
        from app.middleware.perf_guards import BackpressureGuard

        guard = BackpressureGuard(name="api", max_depth=1)
        app = _make_app()
        app.add_middleware(BackpressureMiddleware, guard=guard, max_depth=1)
        # 手动占满深度，使下一个请求被拒
        assert guard.try_enter() is True
        client = TestClient(app)
        resp = client.get("/ping")
        assert resp.status_code == 503
        assert "Retry-After" in resp.headers
        body = resp.json()
        assert body["status"] == 503
        assert body["detail"]
        guard.leave()
        # 深度释放后可再次进入
        assert guard.try_enter() is True
        guard.leave()