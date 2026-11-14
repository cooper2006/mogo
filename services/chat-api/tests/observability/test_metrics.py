"""023 T057/T058 — Prometheus /metrics 端点与维度基数测试。

- T057：/metrics 暴露黄金四信号（延迟/流量/错误率/饱和度）+ chat-api 业务指标；
- T058/T050/FR-12：高基数 label 受控——原始 user_id / session_id / 完整 path
  不得直接作为 label，必须走 path_template 与哈希桶。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_metrics_endpoint_exposes_gold_signals(client):
    """T057：黄金四信号 + chat-api 业务指标在 /metrics 可查。"""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    for name in (
        # 黄金四信号（HTTP 层）
        "mogo_http_requests_total",
        "mogo_http_request_duration_seconds",
        "mogo_http_errors_total",
        "mogo_http_inflight_requests",
        # chat-api 业务指标
        "mogo_chat_llm_calls_total",
        "mogo_chat_llm_tokens_used_total",
        "mogo_chat_messages_sent_total",
        "mogo_chat_sessions_active",
        "mogo_chat_llm_request_duration_seconds",
    ):
        assert name in text, name


def test_high_cardinality_values_map_to_bounded_buckets():
    """T058：任意高基数值哈希到固定桶，组合数有界。"""
    from app.common.high_cardinality import hash_to_bucket

    buckets = {hash_to_bucket(f"user-{i}") for i in range(20000)}
    assert len(buckets) <= 50


def test_http_metrics_do_not_expose_raw_high_cardinality_labels():
    """T050/FR-12：HTTP 指标 label 白名单仅 method/path_template/status_class。"""
    from app.common.observability_base import get_registry

    registry = get_registry("mogo-chat-api")
    http_labels: set[str] = set()
    for metric in registry.collect():
        if metric.name == "mogo_http_requests_total":
            for sample in metric.samples:
                http_labels.update(sample.labels.keys())
    assert http_labels <= {"method", "path_template", "status_class"}, http_labels
    assert "user_id" not in http_labels
    assert "session_id" not in http_labels


def test_get_path_template_normalizes_ids():
    """T050：完整 path → 模板（数字段替换为 {id}）。"""
    from app.common.high_cardinality import get_path_template

    assert (
        get_path_template("/api/chat/sessions/123/messages")
        == "/api/chat/sessions/{id}/messages"
    )


def test_business_metrics_registry_bounded_label_cardinality():
    """T058：业务指标 label 维度组合 ≤ 10000（受控）。"""
    from app.common.observability_base import get_registry
    from app.observability.metrics import register_chat_metrics
    from prometheus_client import CollectorRegistry

    reg: CollectorRegistry = CollectorRegistry()
    register_chat_metrics(reg)
    total = 0
    for metric in reg.collect():
        combos = 1
        for sample in metric.samples:
            combos = max(combos, len(sample.labels))
        total += combos
    assert total < 10000
