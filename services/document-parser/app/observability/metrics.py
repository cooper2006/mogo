"""document-parser 专属业务指标（T049）。

文档解析数、解析耗时、预览转换数等业务黄金信号。
"""
from __future__ import annotations

from typing import Any


def register_document_metrics(registry: Any) -> dict[str, Any]:
    """在给定 registry 上注册 document-parser 业务指标。"""
    from prometheus_client import Counter, Gauge, Histogram

    metrics: dict[str, Any] = {
        "doc_parse_requests_total": Counter(
            "mogo_doc_parse_requests_total",
            "Document parse requests",
            registry=registry,
        ),
        "doc_parse_duration_seconds": Histogram(
            "mogo_doc_parse_duration_seconds",
            "Document parse latency",
            ["doc_type"],
            buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
            registry=registry,
        ),
        "doc_preview_conversions_total": Counter(
            "mogo_doc_preview_conversions_total",
            "Preview conversions",
            registry=registry,
        ),
        "doc_parse_errors_total": Counter(
            "mogo_doc_parse_errors_total",
            "Document parse errors",
            ["error_type"],
            registry=registry,
        ),
        "doc_active_parses": Gauge(
            "mogo_doc_active_parses",
            "Active document parses",
            registry=registry,
        ),
    }
    return metrics
