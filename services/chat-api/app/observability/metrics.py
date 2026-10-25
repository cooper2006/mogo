"""chat-api 专属业务指标（T048）。

LLM 调用数、token 用量、消息数、会话数等业务黄金信号。
"""
from __future__ import annotations

from typing import Any


def register_chat_metrics(registry: Any) -> dict[str, Any]:
    """在给定 registry 上注册 chat-api 业务指标。"""
    from prometheus_client import Counter, Gauge, Histogram

    metrics: dict[str, Any] = {
        "chat_llm_calls_total": Counter(
            "mogo_chat_llm_calls_total",
            "LLM API calls",
            ["provider", "status"],
            registry=registry,
        ),
        "chat_llm_tokens_used": Counter(
            "mogo_chat_llm_tokens_used_total",
            "LLM tokens consumed",
            ["provider", "token_type"],
            registry=registry,
        ),
        "chat_messages_sent_total": Counter(
            "mogo_chat_messages_sent_total",
            "Messages sent",
            registry=registry,
        ),
        "chat_sessions_active": Gauge(
            "mogo_chat_sessions_active",
            "Active chat sessions",
            registry=registry,
        ),
        "chat_llm_request_duration_seconds": Histogram(
            "mogo_chat_llm_request_duration_seconds",
            "LLM request latency",
            ["provider"],
            buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
            registry=registry,
        ),
    }
    return metrics
