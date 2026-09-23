"""LLM gateway resilience (feature 007).

Wraps the existing ``llm/providers`` clients with:

* provider **failover** (primary -> backup) — US1;
* **degradation chain** (high -> mid -> light text model) — US2;
* exponential **backoff retry** (tenacity) — US3;
* metering of failover / degradation / retry events into ``token_usage_logs``.

Text LLM calls only; image generation keeps its own retry inside
``azure_gpt_image`` (clarify OQ-3).
"""

from __future__ import annotations

from .errors import (
    NonRetryableLLMError,
    RetryableLLMError,
    classify_error,
)
from .degradation import (
    DEFAULT_DEGRADATION_CHAIN,
    DegradationError,
    DegradationResult,
    build_chain,
    run_with_degradation,
)
from .failover import FailoverResult, ResilientLLMClient
from .metering import aggregate_usage
from .pricing import DEFAULT_PRICE, MODEL_PRICES, estimate_cost

__all__ = [
    "NonRetryableLLMError",
    "RetryableLLMError",
    "classify_error",
    "FailoverResult",
    "ResilientLLMClient",
    "build_chain",
    "run_with_degradation",
    "DegradationResult",
    "DegradationError",
    "DEFAULT_DEGRADATION_CHAIN",
    "MODEL_PRICES",
    "DEFAULT_PRICE",
    "estimate_cost",
    "aggregate_usage",
]
