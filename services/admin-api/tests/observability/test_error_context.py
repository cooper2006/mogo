"""023 T029 — ERROR 日志上下文测试。

验证 ERROR 日志包含完整上下文：堆栈、请求路径、用户标识、租户标识、下游耗时。
"""
from __future__ import annotations

import json

import pytest

from app.common.observability_base import (
    configure_logging,
    get_logger,
    trace_id_var,
    span_id_var,
    tenant_id_var,
    user_id_var,
)


def _get_entry(capsys) -> dict:
    captured = capsys.readouterr()
    raw = captured.err.strip()
    assert raw, "日志输出为空"
    return json.loads(raw)


def test_error_log_has_stacktrace(capsys):
    """ERROR 日志包含堆栈信息。"""
    configure_logging(service_name="test_service")
    log = get_logger("test_error_stack")
    try:
        raise ValueError("test error for stack trace")
    except ValueError:
        log.exception("error occurred")

    entry = _get_entry(capsys)

    assert entry["level"] == "error"
    # exc_info 应包含堆栈（format_exc_info processor 会把异常格式化为字符串）
    assert "exception" in entry or "exc_info" in entry or "exc" in entry or "traceback" in entry, \
        "ERROR 日志应包含堆栈信息"


def test_error_log_has_request_path(capsys):
    """ERROR 日志包含请求路径。"""
    configure_logging(service_name="test_service")
    log = get_logger("test_error_path")
    log.error("error in request", path="/api/v1/test")

    entry = _get_entry(capsys)

    assert entry["level"] == "error"
    assert "path" in entry, "ERROR 日志应包含请求路径"
    assert entry["path"] == "/api/v1/test"


def test_error_log_has_user_tenant_context(capsys):
    """ERROR 日志包含用户标识和租户标识。"""
    configure_logging(service_name="test_service")
    trace_id_var.set("trace-err-001")
    tenant_id_var.set("tenant-err")
    user_id_var.set("user-err")

    log = get_logger("test_error_ctx")
    log.error("error with context")

    entry = _get_entry(capsys)

    assert entry["level"] == "error"
    assert entry["trace_id"] == "trace-err-001"
    assert entry["tenant_id"] == "tenant-err"
    assert entry["user_id"] == "user-err"

    # 清理
    for var in (trace_id_var, span_id_var, tenant_id_var, user_id_var):
        var.set("")


def test_error_log_has_downstream_duration(capsys):
    """ERROR 日志包含下游耗时字段。"""
    configure_logging(service_name="test_service")
    log = get_logger("test_error_duration")
    log.error("downstream call failed", downstream="llm", duration_ms=1234)

    entry = _get_entry(capsys)

    assert entry["level"] == "error"
    assert "duration_ms" in entry, "ERROR 日志应包含下游耗时"
    assert entry["duration_ms"] == 1234
