"""Resilience error classification (007 T002).

Retryable: 429 (rate limit), 5xx (server error), timeouts, connection errors.
Non-retryable: 401 / 403 (auth) — fail fast, never failover/retry.

The classifier works off HTTP status codes and exception types so it does not
depend on any particular provider SDK.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

# HTTP status codes that indicate a transient failure worth retrying.
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
# Auth failures: never retry, never failover to another provider.
NON_RETRYABLE_STATUS_CODES = frozenset({401, 403})


class LLMResilienceError(Exception):
    """Base class for resilience-layer errors."""


class RetryableLLMError(LLMResilienceError):
    """A transient failure: retry (with backoff) and/or failover."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, provider: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class NonRetryableLLMError(LLMResilienceError):
    """A permanent failure: do not retry or failover."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, provider: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class AllProvidersFailedError(LLMResilienceError):
    """Every configured provider (and degradation step) failed.

    Carries the per-provider failure reasons so the caller can surface an
    aggregated error (FR-10) distinct from a single-provider failure.
    """

    def __init__(self, failures: list[dict[str, Any]]) -> None:
        self.failures = failures
        summary = "; ".join(
            f"{item.get('provider', '?')}: {item.get('reason', '')}" for item in failures
        )
        super().__init__(f"所有供应商均失败（{len(failures)}）：{summary}")


def _status_code_of(error: BaseException) -> Optional[int]:
    for attr in ("status_code", "status", "http_status", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def classify_error(error: BaseException, *, provider: str = "") -> LLMResilienceError:
    """Map an arbitrary provider error to a retryable / non-retryable error.

    Auth (401/403) -> non-retryable. Timeouts / connection errors / 429 / 5xx ->
    retryable. Anything unknown is treated as retryable (fail-open on retry,
    fail-closed on authorization), matching the "retry transients" intent.
    """
    status = _status_code_of(error)
    if status in NON_RETRYABLE_STATUS_CODES:
        return NonRetryableLLMError(str(error), status_code=status, provider=provider)
    if status in RETRYABLE_STATUS_CODES:
        return RetryableLLMError(str(error), status_code=status, provider=provider)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return RetryableLLMError(f"timeout: {error}", provider=provider)
    if isinstance(error, (ConnectionError, OSError)):
        return RetryableLLMError(f"connection error: {error}", provider=provider)
    # Unknown: treat as transient so a retry/failover gets a chance.
    return RetryableLLMError(str(error), status_code=status, provider=provider)


def is_retryable(error: BaseException) -> bool:
    """Whether ``error`` should be retried (True) or fail fast (False)."""
    return isinstance(classify_error(error), RetryableLLMError)
