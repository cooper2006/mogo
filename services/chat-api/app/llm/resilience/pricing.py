"""Model unit-price table (007 T019 / FR-5).

Per-model token pricing, sourced from the shared single source of truth
``app.common.shared_constants`` (058 T015) so chat-api, admin-api dashboard and
analytics stay aligned on one editable table. When a model is absent the
documented default applies (US4: no call is silently un-costed).
"""

from __future__ import annotations

from app.common.shared_constants import DEFAULT_PRICE, MODEL_PRICES


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
