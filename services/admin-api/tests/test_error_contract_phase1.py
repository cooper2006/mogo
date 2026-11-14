"""025 Phase 1（T001–T007）契约测试 — 统一错误结构 + trace_id。

覆盖：
- 422（RequestValidationError）返回 ErrorResponse 结构（RFC 9457 扩展），含
  `code=api.validation_error`、`trace_id`、字段级 `fields[].path`。
- 500（未处理异常）返回 `code=api.internal_error`；生产模式不回显异常详情（FR-12）。
- `X-Trace-ID` 中间件：无上游头则生成并回写；有上游头则沿用（跨服务链路一致）。
- 既有 `detail`（字符串）与 `message` 兼容键并存，且与路由级 HTTPException 形状不冲突。
- 错误码唯一性脚本对三服务生效（T007）。
"""
import os
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("ASKAI_ADMIN_MONGODB_URI", "mongodb://127.0.0.1:27017")

from app.core.error_handler import register_error_handlers  # noqa: E402
from app.core.errors import ApiErrorCode, build_error_payload  # noqa: E402
from app.middleware.trace_id import TRACE_ID_HEADER, TraceIdMiddleware  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _mini_app(*, is_prod: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    register_error_handlers(app, is_prod=is_prod)

    class Body(pydantic.BaseModel):
        name: str
        count: int = 0

    @app.post("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail with /file/path and v1.2.3")

    @app.post("/echo")
    async def echo(body: Body) -> dict:
        return {"ok": True}

    return app


# ────────────────────────────── 422 统一结构 ──────────────────────────────


def test_validation_error_uses_unified_response_structure() -> None:
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    resp = client.post("/echo", json={"name": "x", "count": "not-an-int"})

    assert resp.status_code == 422
    payload = resp.json()
    assert payload["code"] == ApiErrorCode.VALIDATION_ERROR.value == "api.validation_error"
    assert payload["message"] == "Request validation failed"
    assert payload["status"] == 422
    assert payload["title"] == "api.validation_error"
    # FR-11 定位信息：字段名 + JSONPath
    assert payload["field"] == "count"
    assert payload["path"] == "body.count"
    assert isinstance(payload["fields"], list) and payload["fields"]
    assert payload["fields"][0]["path"] == "body.count"
    # trace_id 必填且与响应头一致（FR-10）
    assert payload["trace_id"] and payload["trace_id"] != "unknown"
    assert resp.headers[TRACE_ID_HEADER] == payload["trace_id"]
    # 兼容层：detail 为字符串、message 并存
    assert payload["detail"] == "Request validation failed"


def test_validation_error_detail_stays_backward_compatible_string() -> None:
    """消费方（前端 `typeof detail === 'string'`、`Array.isArray(detail)`）不得被破坏。"""
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    payload = client.post("/echo", json={}).json()
    assert isinstance(payload["detail"], str)


# ────────────────────────────── 500 统一结构 + FR-12 ──────────────────────────────


def test_unhandled_exception_dev_mode_keeps_message_and_adds_code() -> None:
    client = TestClient(_mini_app(is_prod=False), raise_server_exceptions=False)
    resp = client.post("/boom")

    assert resp.status_code == 500
    payload = resp.json()
    assert payload["code"] == "api.internal_error"
    assert payload["trace_id"] == resp.headers[TRACE_ID_HEADER]
    # 非生产环境保留原始文本便于调试（与 QF-447/449 既有口径一致）
    assert "secret internal detail" in payload["message"]


def test_unhandled_exception_prod_mode_leaks_nothing() -> None:
    """FR-12：生产环境错误信息不含内部组件名/版本/文件路径。"""
    client = TestClient(_mini_app(is_prod=True), raise_server_exceptions=False)
    resp = client.post("/boom")

    payload = resp.json()
    assert payload["code"] == "api.internal_error"
    assert payload["message"] == "Internal server error"
    assert payload["detail"] == "Internal server error"
    for leak in ("secret internal detail", "/file/path", "v1.2.3", "RuntimeError", "Traceback"):
        assert leak not in resp.text, f"production error body leaks: {leak}"


# ────────────────────────────── trace_id 中间件 ──────────────────────────────


def test_trace_id_generated_when_absent_and_echoed_in_header() -> None:
    client = TestClient(_mini_app())
    resp = client.post("/echo", json={"name": "x"})

    assert resp.status_code == 200
    trace_id = resp.headers[TRACE_ID_HEADER]
    assert len(trace_id) == 32 and trace_id.isalnum()


def test_trace_id_reuses_upstream_header() -> None:
    """跨服务链路一致（023 追踪同样消费该值）：上游 ID 必须原样沿用。"""
    client = TestClient(_mini_app())
    resp = client.post("/echo", json={"name": "x"}, headers={TRACE_ID_HEADER: "upstream-trace-abc"})

    assert resp.headers[TRACE_ID_HEADER] == "upstream-trace-abc"
    err = client.post("/echo", json={}, headers={TRACE_ID_HEADER: "upstream-trace-abc"}).json()
    assert err["trace_id"] == "upstream-trace-abc"


def test_trace_id_length_capped() -> None:
    client = TestClient(_mini_app())
    resp = client.post("/echo", json={"name": "x"}, headers={TRACE_ID_HEADER: "z" * 500})
    assert len(resp.headers[TRACE_ID_HEADER]) <= 64


# ────────────────────────────── build_error_payload ──────────────────────────────


def test_build_error_payload_maps_rfc9457_and_keeps_compat_keys() -> None:
    payload = build_error_payload(
        code=ApiErrorCode.NOT_FOUND,
        message="Resource not found",
        http_status=404,
        trace_id="t-1",
        detail={"resource": "session"},
    )
    assert payload["code"] == "api.not_found"
    assert payload["type"] == "about:blank"
    assert payload["title"] == "api.not_found"
    assert payload["status"] == 404
    assert payload["trace_id"] == "t-1"
    # 结构化 detail 移到 error_detail，字符串 detail 保持兼容
    assert payload["detail"] == "Resource not found"
    assert payload["error_detail"] == {"resource": "session"}


def test_build_error_payload_docs_url_maps_to_instance() -> None:
    """OQ-1 决策：`docs_url` 映射 RFC 9457 的 `instance`。"""
    payload = build_error_payload(
        code="api.admin.custom",
        message="m",
        http_status=400,
        trace_id="t",
        docs_url="https://docs.example.com/errors#api-admin-custom",
    )
    assert payload["instance"] == payload["docs_url"]
    assert payload["type"] == payload["docs_url"]


def test_default_http_status_covers_every_code() -> None:
    from app.core.errors import DEFAULT_HTTP_STATUS

    for code in ApiErrorCode:
        assert code.value in DEFAULT_HTTP_STATUS, f"{code.value} 缺状态映射"
        assert 100 <= DEFAULT_HTTP_STATUS[code.value] <= 599


# ────────────────────────────── T007 唯一性脚本 ──────────────────────────────


@pytest.mark.parametrize(
    "service",
    ["admin-api", "chat-api", "document-parser"],
)
def test_each_service_ships_registry_and_dictionary(service: str) -> None:
    base = REPO_ROOT / "services" / service / "app" / "core"
    assert (base / "errors.py").exists()
    assert (base / "error_handler.py").exists()
    assert (base / "errors_codes.md").exists()
    assert (REPO_ROOT / "services" / service / "app" / "middleware" / "trace_id.py").exists()


def test_error_codes_uniqueness_script_passes() -> None:
    script = REPO_ROOT / "tools" / "api_check" / "error_codes_uniqueness.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
