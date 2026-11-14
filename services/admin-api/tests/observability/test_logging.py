"""023 T025 — 日志字段稳定性测试。

验证 structlog JSON 输出包含稳定字段：ts/level/service/message/trace_id/span_id/tenant_id/user_id。
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


def test_json_fields_present(capsys):
    """JSON 输出包含基本稳定字段。"""
    configure_logging(service_name="test_service")
    trace_id_var.set("trace-test-001")
    span_id_var.set("span-test-001")
    tenant_id_var.set("tenant-test")
    user_id_var.set("user-test")

    log = get_logger("test_logging_fields")
    log.info("test message")

    entry = _get_entry(capsys)

    for field in ("timestamp", "level", "service", "event"):
        assert field in entry, f"缺少字段 {field}"

    assert entry["level"] == "info"
    assert entry["event"] == "test message"
    assert entry["service"] == "test_service"


def test_trace_context_in_log(capsys):
    """trace_id / span_id / tenant_id / user_id 自动出现在日志中。"""
    configure_logging(service_name="test_service")
    trace_id_var.set("trace-ctx-001")
    span_id_var.set("span-ctx-001")
    tenant_id_var.set("tenant-ctx")
    user_id_var.set("user-ctx")

    log = get_logger("test_logging_ctx")
    log.info("context test")

    entry = _get_entry(capsys)

    assert entry["trace_id"] == "trace-ctx-001"
    assert entry["span_id"] == "span-ctx-001"
    assert entry["tenant_id"] == "tenant-ctx"
    assert entry["user_id"] == "user-ctx"


def test_no_context_no_extra_fields(capsys):
    """无上下文变量时不输出空字段。"""
    configure_logging(service_name="test_service")
    for var in (trace_id_var, span_id_var, tenant_id_var, user_id_var):
        var.set("")

    log = get_logger("test_logging_plain")
    log.info("plain message")

    entry = _get_entry(capsys)

    # 基本字段存在
    for field in ("timestamp", "level", "service", "event"):
        assert field in entry

    # 上下文字段不应出现（_add_trace_context 只加非空值）
    for field in ("trace_id", "span_id", "tenant_id", "user_id"):
        assert field not in entry, f"字段 {field} 不应出现（上下文为空）"
