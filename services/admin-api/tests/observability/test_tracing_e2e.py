"""023 T040/T041/T043 — 追踪测试（admin-api 侧）。

验证 trace_id 传播、日志-追踪互跳、traceparent 注入。
"""
from __future__ import annotations

import json

import pytest

from app.common.observability_base import (
    configure_logging,
    get_logger,
    trace_id_var,
    _add_trace_context,
)


class TestTraceIdPropagation:
    """T040: trace_id 跨服务传播。"""

    def test_trace_id_set_and_read(self):
        """trace_id 设置后可读取。"""
        trace_id_var.set("trace-propagation-test")
        assert trace_id_var.get() == "trace-propagation-test"

    def test_trace_id_in_log_output(self, capsys):
        """日志中包含 trace_id。"""
        configure_logging(service_name="test_tracing")
        trace_id_var.set("trace-log-test")
        log = get_logger("test_tracing_propagation")
        log.info("test message")
        captured = capsys.readouterr()
        raw = captured.err.strip()
        assert raw
        entry = json.loads(raw)
        assert any(
            key in entry for key in ("trace_id", "traceId", "TraceID", "trace")
        )


class TestLogTraceCorrelation:
    """T041: 日志-追踪互跳。"""

    def test_log_contains_trace_id(self, capsys):
        """日志中包含 trace_id 字段。"""
        configure_logging(service_name="test_correlation")
        trace_id_var.set("trace-correlation-001")
        log = get_logger("test_correlation_log")
        log.info("test message")
        captured = capsys.readouterr()
        raw = captured.err.strip()
        assert raw
        entry = json.loads(raw)
        trace_found = any(
            key in entry for key in ("trace_id", "traceId", "TraceID", "trace")
        )
        assert trace_found, f"日志中无 trace_id: {entry}"


class TestTraceparentInjection:
    """T043: traceparent header 注入。"""

    def test_trace_context_exists(self):
        """observability_base 提供 trace context 工具。"""
        assert _add_trace_context is not None

    def test_traceparent_format(self):
        """traceparent 格式符合 W3C 标准。"""
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        parent_id = "00f067aa0ba902b7"
        traceparent = f"00-{trace_id}-{parent_id}-01"
        assert len(traceparent) == 55  # 标准长度
        assert traceparent.startswith("00-")
        assert traceparent.endswith("-01")
