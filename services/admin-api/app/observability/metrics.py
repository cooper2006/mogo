"""admin-api 专属业务指标（T047）。

会话创建数、消息发送数、用户注册数等业务黄金信号。
"""
from __future__ import annotations

from typing import Any


def register_admin_metrics(registry: Any) -> dict[str, Any]:
    """在给定 registry 上注册 admin-api 业务指标。"""
    from prometheus_client import Counter, Gauge, Histogram

    metrics: dict[str, Any] = {
        "admin_sessions_created_total": Counter(
            "mogo_admin_sessions_created_total",
            "Admin sessions created",
            registry=registry,
        ),
        "admin_messages_sent_total": Counter(
            "mogo_admin_messages_sent_total",
            "Messages sent via admin-api",
            registry=registry,
        ),
        "admin_users_registered_total": Counter(
            "mogo_admin_users_registered_total",
            "Users registered",
            registry=registry,
        ),
        "admin_api_request_duration_seconds": Histogram(
            "mogo_admin_api_request_duration_seconds",
            "Admin API request latency",
            ["endpoint", "status_class"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=registry,
        ),
        "admin_active_sessions": Gauge(
            "mogo_admin_active_sessions",
            "Active admin sessions",
            registry=registry,
        ),
    }
    return metrics
