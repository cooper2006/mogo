"""023 Phase 4 — T046 黄金四信号工厂 / T050 高基数标签控制 的行为测试。

覆盖 `services/common/gold_signals.py::create_business_metrics`（FR-9/FR-10：
延迟 histogram / 流量 counter / 错误率 counter / 饱和度 gauge）与
`services/common/high_cardinality.py`（FR-12：hash_to_bucket / sanitize_label /
get_path_template 基数受控）。
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, generate_latest

from app.common.gold_signals import create_business_metrics
from app.common.high_cardinality import (
    get_path_template,
    hash_to_bucket,
    sanitize_label,
)


# ─────────────────────────── T046 黄金四信号 ───────────────────────────


def test_create_business_metrics_registers_four_signal_types():
    registry = CollectorRegistry()
    metrics = create_business_metrics(registry, namespace="mogo_test")

    assert set(metrics) == {
        "business_requests_total",           # 流量 counter
        "business_request_duration_seconds",  # 延迟 histogram
        "business_errors_total",             # 错误率 counter
        "business_queue_depth",              # 饱和度 gauge
        "business_active_workers",           # 饱和度 gauge
    }
    # 四类黄金信号都在给定 registry 上注册（FR-9/FR-10）。
    # 注：prometheus_client 的 Counter 会剥离 `_total` 后缀，collect() 返回剥离名。
    assert {c.name for c in registry.collect()} == {
        "mogo_test_business_requests",
        "mogo_test_business_request_duration_seconds",
        "mogo_test_business_errors",
        "mogo_test_business_queue_depth",
        "mogo_test_business_active_workers",
    }

    # 观测后 /metrics 文本暴露真实契约（Counter 补 _total 后缀，Histogram 出桶）
    metrics["business_requests_total"].labels("chat").inc()
    metrics["business_errors_total"].labels("chat", "timeout").inc()
    metrics["business_request_duration_seconds"].labels("chat", "2xx").observe(0.25)
    metrics["business_queue_depth"].set(3)
    metrics["business_active_workers"].set(7)
    text = generate_latest(registry).decode("utf-8")
    assert "mogo_test_business_requests_total" in text
    assert "mogo_test_business_errors_total" in text
    assert "mogo_test_business_request_duration_seconds_bucket" in text
    assert "mogo_test_business_queue_depth 3.0" in text
    assert "mogo_test_business_active_workers 7.0" in text


def test_create_business_metrics_separate_registries_do_not_collide():
    r1 = CollectorRegistry()
    r2 = CollectorRegistry()
    create_business_metrics(r1, namespace="mogo_a")
    create_business_metrics(r2, namespace="mogo_b")
    assert len(list(r1.collect())) == len(list(r2.collect())) == 5


# ─────────────────────────── T050 高基数标签 ───────────────────────────


def test_hash_to_bucket_bounded_and_deterministic():
    buckets = 50
    seen = set()
    for i in range(5000):
        bucket = hash_to_bucket(f"user-{i}", buckets)
        assert bucket.startswith("bucket_")
        assert 0 <= int(bucket.split("_", 1)[1]) < buckets
        seen.add(bucket)
    # 5000 个不同高基数值只映射到 ≤ 50 桶（FR-12 基数受控）
    assert len(seen) <= buckets
    # 确定性：同输入恒同桶
    assert hash_to_bucket("abc") == hash_to_bucket("abc")


def test_sanitize_label_strips_prometheus_illegal_chars():
    assert sanitize_label("a/b:c") == "a_b_c"
    assert sanitize_label("ok-label_1") == "ok-label_1"
    assert len(sanitize_label("x" * 200)) == 64


def test_get_path_template_collapses_digits():
    assert get_path_template("/api/chat/sessions/123/messages") == (
        "/api/chat/sessions/{id}/messages"
    )
    assert get_path_template("/api/users/42") == "/api/users/{id}"
    # 非数字段保持不变
    assert get_path_template("/api/v1/health") == "/api/v1/health"
