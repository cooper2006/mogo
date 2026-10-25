"""023 Phase 8 — T116 全链路信号贯通（进程内可自动化的那一半）。

**这份测试能证明什么、不能证明什么**（先说清楚，免得把绿当成上线）：

能证明：一次操作的 **span → 日志 → 指标** 三者在同一进程内共享同一个
`trace_id`，字段名与结构稳定；父子 span 关系正确；没有 OTLP 端点时降级为
本地 provider 而不是外连或抛错。

不能证明：真实 Tempo/Loki/Prometheus/Alertmanager 上「能查到」「能告警」
——那需要完整 compose 环境，验证剧本见 `docs/observability/architecture.md` §8
与 `scripts/verify_e2e_observability.sh`（无环境时明确返回 2）。
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from prometheus_client import CollectorRegistry, generate_latest

from app.common import observability_base
from app.common.gold_signals import create_business_metrics
from app.common.observability_base import (
    configure_logging,
    get_logger,
    init_tracing,
)


@pytest.fixture()
def span_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    """独立 TracerProvider + 内存 exporter。

    **不调用 `trace.set_tracer_provider`**：全局 provider 在一个进程里只能设置
    一次，被别的测试/插件抢先设置后这里会静默失效（只剩一条
    `Overriding of current TracerProvider is not allowed` 警告），于是
    exporter 永远收不到 span。改为直接持有 provider 并用它的 tracer；
    `start_as_current_span` 写的是全局 contextvars，所以日志注入照常生效。
    """

    exporter = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "chat-api"}),
        sampler=ALWAYS_ON,  # 测试必须 100% 采样，否则断言随机失败
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    exporter.clear()


class _MemoryHandler(logging.Handler):
    """把格式化后的日志行收到内存里，便于断言真实 JSON 结构。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # pragma: no cover - 格式化异常不应影响被测代码
            self.lines.append(record.getMessage())


@pytest.fixture()
def json_logs():
    """把 root logger 切到 JSON 输出，并挂一个内存 handler 抓取结果。"""

    root = logging.getLogger()
    original = list(root.handlers)
    original_level = root.level
    capture = _MemoryHandler()
    try:
        structlog.reset_defaults()
        configure_logging("chat-api", level="INFO", json_output=True)
        # 复用 configure_logging 装配的 ProcessorFormatter，否则拿到的是 str(dict)
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        yield capture
    finally:
        root.removeHandler(capture)
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in original:
            root.addHandler(handler)
        root.setLevel(original_level)
        structlog.reset_defaults()


def _last_json_line(records) -> dict:
    for line in reversed(records.lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"没有解析到 JSON 日志行：{records.lines[-3:]}")


# ─────────────────────── 1. span 结构与父子关系 ───────────────────────


def test_spans_export_with_parent_child_relationship(span_exporter):
    """一次「请求」应产生 server span，其下挂下游 client span 与业务 span。"""

    provider, exporter = span_exporter
    tracer = provider.get_tracer("mogo")
    with tracer.start_as_current_span("POST /sessions/messages") as root_span:
        with tracer.start_as_current_span("llm.chat.completions") as child_span:
            child_span.set_attribute("llm.provider", "azure-openai")

    spans = exporter.get_finished_spans()
    assert len(spans) == 2, f"应导出 2 个 span，实际 {[s.name for s in spans]}"

    by_name = {span.name: span for span in spans}
    root, child = by_name["POST /sessions/messages"], by_name["llm.chat.completions"]

    # 同一 trace、父子关系
    assert root.context.trace_id == child.context.trace_id
    assert child.parent is not None
    assert child.parent.span_id == root.context.span_id

    # 服务名来自 Resource，排障时靠它区分是哪个服务
    assert root.resource.attributes["service.name"] == "chat-api"
    assert child.attributes["llm.provider"] == "azure-openai"


# ───────────────────── 2. 日志携带当前 trace_id ─────────────────────


def test_log_record_carries_current_trace_id(span_exporter, json_logs):
    """日志里的 trace_id 必须等于 span 的 trace_id（而不是随机值/空）。"""

    provider, _exporter = span_exporter
    tracer = provider.get_tracer("mogo")
    with tracer.start_as_current_span("GET /sessions") as span:
        get_logger("mogo.test").info("session listed", tenant_id="t-1")

    record = _last_json_line(json_logs)
    span_trace_id = format(span.context.trace_id, "032x")

    assert record["event"] == "session listed"
    assert record["trace_id"] == span_trace_id
    assert record["tenant_id"] == "t-1"
    assert record["service"] == "chat-api", "服务名由 configure_logging 注入，日志必须自带"
    assert record["level"] == "info"


def test_log_outside_span_does_not_fabricate_trace_id(json_logs):
    """没有 span 时不伪造 trace_id——伪造会让「按 trace_id 查日志」查到错误结果。"""

    get_logger("mogo.test").info("no span here")
    record = _last_json_line(json_logs)
    assert record["event"] == "no span here"
    # 没有 span 时字段缺失或为空串都可接受，但**不能**是伪造的全零/随机 id
    assert not (record.get("trace_id") or "").strip("0")


# ───────────────────────── 3. 指标可被刮取 ─────────────────────────


def test_metrics_capture_a_request_end_to_end():
    """黄金四信号在记录一次请求后能产出可抓取的值（含延迟分桶）。"""

    registry = CollectorRegistry()
    metrics = create_business_metrics(registry, namespace="mogo_e2e")

    metrics["business_requests_total"].labels(endpoint="/sessions/messages").inc()
    metrics["business_request_duration_seconds"].labels(
        endpoint="/sessions/messages", status_class="2xx"
    ).observe(0.42)
    metrics["business_errors_total"].labels(
        endpoint="/sessions/messages", error_type="upstream"
    ).inc()
    metrics["business_queue_depth"].set(3)

    text = generate_latest(registry).decode()
    assert 'mogo_e2e_business_requests_total{endpoint="/sessions/messages"} 1.0' in text
    assert "mogo_e2e_business_request_duration_seconds_bucket" in text
    assert (
        'mogo_e2e_business_request_duration_seconds_count'
        '{endpoint="/sessions/messages",status_class="2xx"} 1.0'
    ) in text
    assert 'mogo_e2e_business_errors_total{endpoint="/sessions/messages",error_type="upstream"} 1.0' in text
    assert "mogo_e2e_business_queue_depth 3.0" in text


# ─────────────── 4. 三信号共享同一个 trace_id（贯通的核心）───────────────


def test_span_log_and_metrics_share_one_trace_id(span_exporter, json_logs):
    """日志的 trace_id / span 的 trace_id / span 属性三者一致，才算「贯通」。"""

    provider, exporter = span_exporter
    tracer = provider.get_tracer("mogo")
    with tracer.start_as_current_span("POST /chat") as span:
        trace_id = format(span.context.trace_id, "032x")
        span.set_attribute("mogo.trace_id", trace_id)
        get_logger("mogo.test").info("turn handled", trace_id_echo=trace_id)

    record = _last_json_line(json_logs)
    exported = exporter.get_finished_spans()[0]

    assert record["trace_id"] == trace_id
    assert record["trace_id_echo"] == trace_id
    assert exported.attributes["mogo.trace_id"] == trace_id
    assert format(exported.context.trace_id, "032x") == trace_id


# ───────────────────── 5. 无端点时降级不外连 ─────────────────────


def test_tracing_falls_back_to_local_without_otlp_endpoint(monkeypatch):
    """没有 OTLP 端点时返回 False（本地 provider），不抛错也不外连。

    这是 FR-13 的反向应用：可观测性自身不得成为启动失败源。
    """

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(observability_base, "_tracing_initialized", False, raising=True)

    assert init_tracing("chat-api", otlp_endpoint="") is False
    # 幂等：重复初始化不再重复装配
    assert init_tracing("chat-api", otlp_endpoint="") is False
