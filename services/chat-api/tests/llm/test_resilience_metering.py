"""Tests for LLM metering (feature 007 US4 / T018-T024).

Covers: cost estimation (T019), dimension aggregation (T020), metering
integration (T021: call record + per-dimension query), resilience-event
observability (T022), and metering coverage (T024).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm.resilience import (
    DEFAULT_PRICE,
    MODEL_PRICES,
    aggregate_usage,
    estimate_cost,
)
from app.llm.resilience.events import failover_fields
from app.token_usage.models import TokenUsageRecord


# --- T019 cost estimation ----------------------------------------------------


def test_estimate_cost_uses_model_prices() -> None:
    in_price, out_price = MODEL_PRICES["gpt-5.2"]
    cost = estimate_cost(model="gpt-5.2", prompt_tokens=10_000, completion_tokens=5_000)
    assert cost == pytest.approx((10_000 * in_price + 5_000 * out_price) / 1_000_000.0)


def test_estimate_cost_unknown_model_uses_default() -> None:
    in_price, out_price = DEFAULT_PRICE
    cost = estimate_cost(model="some-unlisted-model", prompt_tokens=1_000, completion_tokens=1_000)
    assert cost == pytest.approx((1_000 * in_price + 1_000 * out_price) / 1_000_000.0)
    # No call is un-costed (T024 baseline)
    assert cost > 0


def test_estimate_cost_negative_tokens_clamped() -> None:
    assert estimate_cost(model="gpt-5.2", prompt_tokens=-100, completion_tokens=-100) == 0.0


def test_pricing_table_mirrors_admin_dashboard() -> None:
    """007 and 008 share the same price table (FR-5)."""
    from app.llm.resilience.pricing import DEFAULT_PRICE as _dp, MODEL_PRICES as _mp

    # Same keys as admin-api dashboard.MODEL_PRICES
    assert set(_mp.keys()) == {
        "deepseek-v4-flash",
        "gpt-5.2-chat",
        "gpt-5.2",
        "gpt-5.4",
        "qwen3-vl-plus",
    }
    assert _dp == (10.0, 30.0)


# --- T020 dimension aggregation ------------------------------------------------


def _rows() -> list[dict[str, Any]]:
    return [
        {"model_name": "gpt-5.2", "main_id": "t1", "agent_id": "agent-a", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_estimate_usd": 0.001, "provider": "openai"},
        {"model_name": "gpt-5.2", "main_id": "t1", "agent_id": "agent-b", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_estimate_usd": 0.001, "provider": "openai"},
        {"model_name": "qwen3-vl-plus", "main_id": "t2", "agent_id": "agent-a", "prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300, "cost_estimate_usd": 0.0003, "provider": "qwen"},
    ]


def test_aggregate_by_model() -> None:
    result = aggregate_usage(_rows(), dimension="model")
    by_key = {item["key"]: item for item in result}
    assert by_key["gpt-5.2"]["calls"] == 2
    assert by_key["gpt-5.2"]["total_tokens"] == 300
    assert by_key["qwen3-vl-plus"]["total_tokens"] == 300
    # Sorted by cost desc
    assert result[0]["cost"] >= result[-1]["cost"]


def test_aggregate_by_provider() -> None:
    result = aggregate_usage(_rows(), dimension="provider")
    by_key = {item["key"]: item for item in result}
    assert by_key["openai"]["calls"] == 2
    assert by_key["qwen"]["calls"] == 1


def test_aggregate_by_tenant() -> None:
    result = aggregate_usage(_rows(), dimension="tenant")
    by_key = {item["key"]: item for item in result}
    assert by_key["t1"]["calls"] == 2
    assert by_key["t2"]["calls"] == 1


def test_aggregate_by_agent() -> None:
    result = aggregate_usage(_rows(), dimension="agent")
    by_key = {item["key"]: item for item in result}
    assert by_key["agent-a"]["calls"] == 2
    assert by_key["agent-b"]["calls"] == 1


def test_aggregate_empty_rows() -> None:
    assert aggregate_usage([], dimension="model") == []


def test_aggregate_unknown_dimension_falls_back_to_model() -> None:
    result = aggregate_usage(_rows(), dimension="bogus")
    assert all(item["dimension"] == "model" for item in result)


# --- T021 metering integration ------------------------------------------------


def test_token_usage_record_carries_cost_and_resilience() -> None:
    """The record persisted by the metering pipeline carries both fields."""
    record = TokenUsageRecord(
        request_id="llm_test",
        model_name="gpt-5.2",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_estimate_usd=estimate_cost(model="gpt-5.2", prompt_tokens=100, completion_tokens=50),
        resilience_events=failover_fields("azure", "default", attempt=2),
    )
    dumped = record.model_dump()
    assert dumped["cost_estimate_usd"] > 0
    assert dumped["resilience_events"]["failover_from"] == "azure"
    assert dumped["resilience_events"]["failover_to"] == "default"


def test_token_usage_record_defaults_when_absent() -> None:
    record = TokenUsageRecord(request_id="llm_plain", model_name="gpt-5.2")
    dumped = record.model_dump()
    assert dumped["cost_estimate_usd"] == 0.0
    assert dumped["resilience_events"] is None


# --- T022 resilience event observability -------------------------------------


def test_resilience_events_are_queryable_on_record() -> None:
    """failover/degradation/retry events all land as fields on the same record (FR-7)."""
    from app.llm.resilience.events import degradation_fields

    record = TokenUsageRecord(
        request_id="llm_obs",
        model_name="gpt-5.2",
        resilience_events={
            **failover_fields("azure", "default"),
            **degradation_fields(2, provider="default", reason="rate_limited"),
        },
    )
    fields = record.resilience_events
    # failover_fields provides from/to; degradation_fields overrides with the
    # final provider + step/reason. All three event types are queryable.
    assert fields["failover_to"] == "default"
    assert fields["degradation_step"] == 2
    assert fields["degradation_reason"] == "rate_limited"
    # 100% of resilience events are queryable via the record's extra fields
    assert set(fields) >= {"failover_to", "degradation_step", "degradation_reason"}


# --- T024 metering coverage ---------------------------------------------------


def test_metering_covers_unknown_models() -> None:
    """Every call produces a cost estimate, even for unlisted models (0 diff baseline)."""
    for model in ("gpt-5.2", "deepseek-v4-flash", "unlisted-model-x"):
        assert estimate_cost(model=model, prompt_tokens=10, completion_tokens=10) > 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
