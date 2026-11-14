"""023 T093 — 限流与背压（FR-25）。

队列深度超限返回 429（不排队、不崩溃）；探针路径豁免；租户维度独立计数。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.common.dependency_guard import BackpressureError, BackpressureGuard, RateLimiter
from app.common.resilience_middleware import ResilienceMiddleware


class _FakeApp:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _run(middleware, scope=None):
    messages: list[dict] = []
    sent_start = {"done": False}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            sent_start["done"] = True

    async def receive():
        return {"type": "http.request"}

    asyncio.run(middleware(scope or _scope(), receive, send))
    return messages


def _scope(path: str = "/api/chat/sessions", headers: list | None = None) -> dict:
    return {
        "type": "http",
        "path": path,
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "state": {},
    }


def _status(messages) -> int:
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


def _body(messages) -> dict:
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return json.loads(raw.decode("utf-8"))


# ── BackpressureGuard 单元行为 ──────────────────────────────
def test_guard_rejects_beyond_max_depth():
    guard = BackpressureGuard("svc", max_depth=2)
    assert guard.try_enter() is True
    assert guard.try_enter() is True
    assert guard.try_enter() is False
    assert guard.depth == 2
    guard.leave()
    assert guard.try_enter() is True


def test_guard_enter_raises_backpressure_error():
    guard = BackpressureGuard("svc", max_depth=1)
    guard.enter()
    with pytest.raises(BackpressureError) as exc:
        guard.enter()
    assert exc.value.limit == 1
    assert exc.value.retry_after_seconds == 1.0


def test_guard_invalid_depth_rejected():
    with pytest.raises(ValueError):
        BackpressureGuard("svc", max_depth=0)


# ── RateLimiter 单元行为 ────────────────────────────────────
def test_rate_limiter_allows_burst_then_rejects():
    limiter = RateLimiter(qps=1.0, burst=2, max_concurrent=10, clock=lambda: 1000.0)
    assert limiter.acquire("t1").allowed is True
    assert limiter.acquire("t1").allowed is True
    rejected = limiter.acquire("t1")
    assert rejected.allowed is False
    assert rejected.reason == "qps"
    assert rejected.retry_after_seconds > 0


def test_rate_limiter_tenants_are_independent():
    limiter = RateLimiter(qps=1.0, burst=1, max_concurrent=10, clock=lambda: 1000.0)
    assert limiter.acquire("t1").allowed is True
    assert limiter.acquire("t1").allowed is False
    # 另一个租户仍有自己的令牌。
    assert limiter.acquire("t2").allowed is True


def test_rate_limiter_enforces_concurrency():
    limiter = RateLimiter(qps=100.0, burst=100, max_concurrent=1, clock=lambda: 1000.0)
    assert limiter.acquire("t1").allowed is True
    rejected = limiter.acquire("t1")
    assert rejected.allowed is False
    assert rejected.reason == "concurrency"
    limiter.release("t1")
    assert limiter.acquire("t1").allowed is True


# ── 中间件端到端（429 而非排队/崩溃）────────────────────────
def test_middleware_returns_429_when_queue_is_full():
    app = _FakeApp()
    guard = BackpressureGuard("svc", max_depth=1)
    mw = ResilienceMiddleware(app, service_name="svc", backpressure=guard)

    # 先占满一个槽，模拟已有请求在途。
    assert guard.try_enter() is True
    messages = _run(mw)

    assert _status(messages) == 429
    payload = _body(messages)
    assert payload["error"]["code"] == "backpressure_exceeded"
    assert payload["error"]["service"] == "svc"
    headers = dict(next(m["headers"] for m in messages if m["type"] == "http.response.start"))
    assert headers[b"retry-after"] == b"1"
    assert app.calls == 0, "被背压拒绝的请求不应进入业务处理"


def test_middleware_returns_429_on_rate_limit():
    app = _FakeApp()
    limiter = RateLimiter(qps=1.0, burst=1, max_concurrent=10, clock=lambda: 1000.0)
    mw = ResilienceMiddleware(app, service_name="svc", rate_limiter=limiter)

    # 第一次放行（测试应用会立即返回，令牌被 release，但令牌桶已扣减）。
    assert _status(_run(mw)) == 200
    messages = _run(mw)
    assert _status(messages) == 429
    assert _body(messages)["error"]["code"] == "rate_limited"


def test_middleware_exempts_probe_paths():
    """/health /ready /metrics 不能被限流：过载时也要能报出「我过载了」。"""
    app = _FakeApp()
    guard = BackpressureGuard("svc", max_depth=1)
    guard.try_enter()
    mw = ResilienceMiddleware(app, service_name="svc", backpressure=guard)
    for path in ("/health", "/ready", "/metrics"):
        assert _status(_run(mw, _scope(path=path))) == 200


def test_middleware_records_rejections_via_hook():
    app = _FakeApp()
    seen: list[str] = []
    guard = BackpressureGuard("svc", max_depth=1)
    guard.try_enter()
    mw = ResilienceMiddleware(app, service_name="svc", backpressure=guard, on_reject=seen.append)
    _run(mw)
    assert seen == ["backpressure_exceeded"]


def test_middleware_uses_tenant_header_as_limit_key():
    app = _FakeApp()
    limiter = RateLimiter(qps=1.0, burst=1, max_concurrent=10, clock=lambda: 1000.0)
    mw = ResilienceMiddleware(app, service_name="svc", rate_limiter=limiter)
    ok = _scope(headers=[(b"x-tenant-id", b"tenant-a")])
    other = _scope(headers=[(b"x-tenant-id", b"tenant-b")])
    assert _status(_run(mw, ok)) == 200
    assert _status(_run(mw, ok)) == 429
    assert _status(_run(mw, other)) == 200
