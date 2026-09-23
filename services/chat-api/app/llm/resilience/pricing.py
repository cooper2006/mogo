"""Model unit-price table (007 T019 / FR-5).

The single source of truth for per-model token pricing, shared by 007
metering (cost estimation at call time) and 008 dashboard (reconciliation /
aggregation). The table is *mirrored* from ``admin-api``'s
``api/routes/dashboard.py`` MODEL_PRICES so the two services stay aligned
(same prices, same default) without a cross-service import. When a model is
absent the documented default applies (US4: no call is silently un-costed).
"""

from __future__ import annotations

from typing import Tuple

# model -> (input price, output price) per 1M tokens (USD)
MODEL_PRICES: dict[str, Tuple[float, float]] = {
    "deepseek-v4-flash": (0.5, 1.5),
    "gpt-5.2-chat": (35.0, 110.0),
    "gpt-5.2": (35.0, 110.0),
    "gpt-5.4": (100.0, 300.0),
    "qwen3-vl-plus": (10.0, 10.0),
}

DEFAULT_PRICE: Tuple[float, float] = (10.0, 30.0)


def estimate_cost(
    *,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> float:
    """Estimated USD cost of one call (token count x unit price, FR-5).

    Unknown models fall back to :data:`DEFAULT_PRICE` — the call is never
    un-costed (008 reconciliation baseline: per-model costs sum to the
    total, 0 discrepancy, US2 FR-6 / T026).
    """
    in_price, out_price = MODEL_PRICES.get(str(model or "").strip(), DEFAULT_PRICE)
    return (max(0, prompt_tokens) * in_price + max(0, completion_tokens) * out_price) / 1_000_000.0


__all__ = ["MODEL_PRICES", "DEFAULT_PRICE", "estimate_cost"]
