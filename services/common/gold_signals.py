"""黄金四信号指标定义（FR-9/FR-10）。

延迟 histogram / 流量 counter / 错误率 counter / 饱和度 gauge。
HTTP 层指标由 observability_base.init_metrics() 创建；本模块提供
业务层黄金信号指标工厂，供各服务在 observability/metrics.py 中注册。
"""
from __future__ import annotations

from typing import Any


def create_business_metrics(registry: Any, namespace: str = "mogo") -> dict[str, Any]:
    """在给定 registry 上创建业务黄金信号指标。

    Args:
        registry: prometheus CollectorRegistry
        namespace: 指标名前缀（如 mogo_admin / mogo_chat / mogo_document）

    Returns:
        指标字典，供服务层 observe
    """
    from prometheus_client import Counter, Gauge, Histogram

    ns = f"{namespace}_"
    metrics: dict[str, Any] = {
        # --- 流量 counter ---
        "business_requests_total": Counter(
            f"{ns}business_requests_total",
            "Business-level request count",
            ["endpoint"],
            registry=registry,
        ),
        # --- 延迟 histogram ---
        "business_request_duration_seconds": Histogram(
            f"{ns}business_request_duration_seconds",
            "Business-level request latency",
            ["endpoint", "status_class"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=registry,
        ),
        # --- 错误率 counter ---
        "business_errors_total": Counter(
            f"{ns}business_errors_total",
            "Business-level error count",
            ["endpoint", "error_type"],
            registry=registry,
        ),
        # --- 饱和度 gauge ---
        "business_queue_depth": Gauge(
            f"{ns}business_queue_depth",
            "Business queue depth (saturation proxy)",
            registry=registry,
        ),
        "business_active_workers": Gauge(
            f"{ns}business_active_workers",
            "Active workers (saturation proxy)",
            registry=registry,
        ),
    }
    return metrics
