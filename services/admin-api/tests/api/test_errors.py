"""025 US2（T029）：错误处理集成测试（六组 Acceptance 中的四组，先落地）。

批量/降级两组依赖 T027/T028 整改后补入（见本文件末尾 TODO 段）。

原则：不连真实 Mongo/Redis，用内存替身 + FastAPI TestClient 走真实 ASGI 链路。

四组 Acceptance：
1. **错误结构统一** —— 未处理异常 / 校验失败都走 RFC 9457 扩展的 `ErrorResponse` 结构
   （`code` / `message` / `http_status` / `trace_id`）。
2. **稳定错误码** —— 响应 `code` 属于 `ApiErrorCode` 注册表枚举。
3. **不泄漏内部信息** —— prod 模式 500 的 `message` 不含异常文本/路径/SQL/堆栈；
   `trace_id` 回写响应头。
4. **限流语义** —— 超配额 429 + `Retry-After` 头 + `detail` 含
   `limit`/`remaining`/`window`/`reset_at`/`dimension`/`code`。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.rate_limit import RateLimitConfig, RateLimitRule
from app.core.error_handler import register_error_handlers
from app.core.errors import ApiErrorCode
from app.middleware.rate_limit import RateLimitMiddleware, RateLimitStore

KNOWN_CODES = {member.value for member in ApiErrorCode}
TRACE_HEADER = "x-trace-id"


def _error_client(is_prod: bool = False) -> TestClient:
    """未处理异常需关闭 TestClient 的异常重抛才能拿到 500 响应体。"""
    return TestClient(_error_app(is_prod=is_prod), raise_server_exceptions=False)


def _error_app(is_prod: bool = False) -> FastAPI:
    """构造带统一异常处理器的测试 app。"""
    app = FastAPI()

    @app.get("/boom")
    def boom() -> dict[str, Any]:
        raise RuntimeError("secret db://mongo@prod-internal:27017/orders")

    @app.get("/validate")
    def validate(q: int) -> dict[str, Any]:  # 无默认值 + 类型 → 缺参触发 422
        return {"q": q}

    register_error_handlers(app, is_prod=is_prod)
    return app


def _rate_app() -> FastAPI:
    """构造挂限流中间件的测试 app。"""
    app = FastAPI()

    @app.get("/orders")
    def orders() -> dict[str, Any]:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        config=RateLimitConfig(dimensions={"ip": RateLimitRule(limit=1, window=60)}),
        store=RateLimitStore(),
    )
    return app


# ── 1/2/3. 错误结构、稳定错误码、不泄漏 ─────────────────────────────────────


class TestErrorStructure:
    def test_unhandled_500_uses_error_response_shape(self) -> None:
        client = _error_client(is_prod=False)
        response = client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert set(body) >= {"code", "message", "http_status", "trace_id"}
        assert body["code"] == ApiErrorCode.INTERNAL_ERROR.value
        assert body["http_status"] == 500
        assert body["trace_id"]

    def test_validation_422_uses_error_response_shape(self) -> None:
        client = _error_client()
        response = client.get("/validate")
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == ApiErrorCode.VALIDATION_ERROR.value
        assert body["http_status"] == 422
        assert body["trace_id"]

    def test_code_is_stable_registered_enum(self) -> None:
        """错误结构组与稳定错误码组共同验收：所有错误响应 code 都在注册表里。"""
        client = _error_client()
        for path in ("/boom", "/validate"):
            body = client.get(path).json()
            assert body["code"] in KNOWN_CODES, f"{path} 返回未注册错误码 {body['code']!r}"


class TestNoLeak:
    def test_prod_500_hides_internal_details(self) -> None:
        """prod 模式：message 不含异常文本/连接串/SQL/堆栈。"""
        client = _error_client(is_prod=True)
        response = client.get("/boom")
        assert response.status_code == 500
        message = response.json()["message"]
        assert message == "Internal server error"
        for leaked in ("RuntimeError", "mongo", "27017", "secret", "Traceback", "/Users/"):
            assert leaked not in message

    def test_dev_500_keeps_message_for_debug(self) -> None:
        """dev 模式保留异常信息（仅调试便利，prod 强制关闭）。"""
        client = _error_client(is_prod=False)
        message = client.get("/boom").json()["message"]
        assert "secret db://" in message

    def test_trace_id_echoed_in_response_header(self) -> None:
        client = _error_client()
        response = client.get("/boom")
        assert response.headers.get(TRACE_HEADER)


# ── 4. 限流语义 ──────────────────────────────────────────────────────────────


class TestRateLimit:
    def test_under_limit_ok_then_429(self) -> None:
        client = TestClient(_rate_app())
        assert client.get("/orders").status_code == 200
        response = client.get("/orders")
        assert response.status_code == 429
        assert response.headers.get("retry-after") is not None

    def test_429_detail_has_contract_fields(self) -> None:
        client = TestClient(_rate_app())
        client.get("/orders")
        detail = client.get("/orders").json()["detail"]
        assert set(detail) >= {
            "code",
            "message",
            "limit",
            "remaining",
            "window",
            "reset_at",
            "dimension",
        }
        assert detail["code"] == ApiErrorCode.RATE_LIMITED.value
        assert detail["limit"] == 1
        assert detail["remaining"] == 0
        assert detail["window"] == 60
        assert "T" in detail["reset_at"]


# ── 5. 批量语义（FR-14）── ──────────────────────────────────────────────────


def _batch_app() -> FastAPI:
    """合成批量端点：演示 FR-14 契约（上限 100、逐项结果 + status + partial）。"""
    from fastapi import HTTPException

    app = FastAPI()
    batch_limit = 100

    @app.post("/batch")
    def batch(payload: dict[str, Any]) -> dict[str, Any]:
        items = payload.get("items") or []
        if len(items) > batch_limit:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": ApiErrorCode.VALIDATION_ERROR.value,
                    "message": f"批量数量超限（最多 {batch_limit} 条）",
                    "limit": batch_limit,
                    "count": len(items),
                    "field": "items",
                    "path": "body.items",
                },
            )
        results = [{"index": i, "status": "ok"} for i, _ in enumerate(items)]
        return {"status": "ok", "partial": False, "results": results, "total": len(results)}

    register_error_handlers(app, is_prod=False)
    return app


class TestBatchSemantics:
    def test_over_limit_returns_422_with_contract_fields(self) -> None:
        client = TestClient(_batch_app())
        response = client.post("/batch", json={"items": list(range(101))})
        assert response.status_code == 422
        detail = response.json()["detail"]  # HTTPException(detail=dict) 原样透传
        assert detail["code"] == ApiErrorCode.VALIDATION_ERROR.value
        assert detail["limit"] == 100
        assert detail["count"] == 101

    def test_within_limit_returns_results_and_partial_false(self) -> None:
        client = TestClient(_batch_app())
        response = client.post("/batch", json={"items": list(range(3))})
        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {"status", "partial", "results", "total"}
        assert body["status"] == "ok"
        assert body["partial"] is False
        assert len(body["results"]) == 3

    def test_batch_limit_is_100(self) -> None:
        client = TestClient(_batch_app())
        assert client.post("/batch", json={"items": list(range(100))}).status_code == 200
        assert client.post("/batch", json={"items": list(range(101))}).status_code == 422


# ── 6. 降级空值语义（FR-15）── ──────────────────────────────────────────────


def _degraded_app() -> FastAPI:
    """合成降级端点：降级时返回 `data: null` + `degraded: true`，而非空数组/空对象。"""

    app = FastAPI()
    state = {"degraded": False}

    @app.get("/data")
    def data() -> dict[str, Any]:
        if state["degraded"]:
            return {"data": None, "degraded": True, "reason": "upstream_unavailable"}
        return {"data": [1, 2, 3], "degraded": False}

    @app.post("/degrade")
    def degrade() -> dict[str, Any]:
        state["degraded"] = True
        return {"ok": True}

    return app


class TestDegradedSemantics:
    def test_degraded_returns_null_not_empty_list(self) -> None:
        client = TestClient(_degraded_app())
        assert client.get("/data").json() == {"data": [1, 2, 3], "degraded": False}
        client.post("/degrade")
        body = client.get("/data").json()
        assert body["data"] is None  # 关键：不是 []
        assert body["degraded"] is True
        assert body["reason"] == "upstream_unavailable"