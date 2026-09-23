"""Exponential backoff retry primitive (007 T006 / US3).

Uses ``tenacity`` (already a dependency, see requirements.txt) with the same
defaults as the existing ``azure_gpt_image`` provider so behavior does not drift:

* base 1.5s, cap 30s, jitter +/-10%, max 3 attempts;
* retryable: 429 / 5xx / timeout; non-retryable: 401 / 403 (fail fast).

All values are configurable (FR-3 / FR-8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .errors import NonRetryableLLMError, RetryableLLMError, classify_error

T = TypeVar("T")

# Defaults aligned with ``azure_gpt_image.RetryConfig`` (clarify OQ-2).
DEFAULT_RETRY_BASE_SECONDS = 1.5
DEFAULT_RETRY_MAX_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_JITTER_SECONDS = 0.15  # ~+/-10% of the 1.5s base


@dataclass(frozen=True)
class RetryPolicy:
    base_seconds: float = DEFAULT_RETRY_BASE_SECONDS
    max_seconds: float = DEFAULT_RETRY_MAX_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    jitter_seconds: float = DEFAULT_JITTER_SECONDS


def _should_retry(error: BaseException) -> bool:
    """Retry transient failures only; auth errors fail immediately."""
    classified = classify_error(error)
    if isinstance(classified, NonRetryableLLMError):
        return False
    return isinstance(classified, RetryableLLMError)


async def retry_with_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> T:
    """Run ``operation`` with exponential backoff + jitter.

    Non-retryable errors are re-raised immediately, without waiting. On exhausting
    the attempt budget, the last error is re-raised (wrapped for context).
    """
    cfg = policy or RetryPolicy()
    attempt_counter = {"n": 0}

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max(1, cfg.max_attempts)),
        wait=wait_exponential_jitter(
            initial=cfg.base_seconds,
            max=cfg.max_seconds,
            jitter=cfg.jitter_seconds,
        ),
        retry=retry_if_exception(_should_retry),
        reraise=True,
    ):
        with attempt:
            attempt_counter["n"] += 1
            try:
                return await operation()
            except BaseException as error:  # noqa: BLE001 - re-classified below
                classified = classify_error(error)
                if isinstance(classified, NonRetryableLLMError):
                    raise classified from error
                if on_retry is not None:
                    on_retry(attempt_counter["n"], error)
                raise classified from error
    # AsyncRetrying with reraise=True always returns or raises; this is unreachable.
    raise RetryError(None)  # pragma: no cover
