"""Bounded retries for idempotent DSH persistence operations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from pymongo.errors import (
    AutoReconnect,
    BulkWriteError,
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
    WTimeoutError,
)


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class PersistenceRetryPolicy:
    """Small retry budget so a transient database fault does not fail a turn."""

    max_attempts: int = 4
    initial_delay_seconds: float = 0.05
    max_delay_seconds: float = 0.4


DEFAULT_PERSISTENCE_RETRY_POLICY = PersistenceRetryPolicy()

# MongoDB retryable-write error codes. Supporting the codes as well as error
# labels keeps this compatible with the PyMongo version used by the project.
_RETRYABLE_OPERATION_CODES = {
    6,
    7,
    89,
    91,
    189,
    262,
    9001,
    10107,
    11600,
    11602,
    13435,
    13436,
}


def is_retryable_persistence_error(error: BaseException) -> bool:
    """Return whether repeating an idempotent MongoDB write is safe/useful."""

    if isinstance(
        error,
        (
            AutoReconnect,
            ConnectionFailure,
            NetworkTimeout,
            ServerSelectionTimeoutError,
            ExecutionTimeout,
            WTimeoutError,
            DuplicateKeyError,
        ),
    ):
        return True
    if isinstance(error, BulkWriteError):
        details = error.details or {}
        write_errors = details.get("writeErrors") or []
        if write_errors and all(
            int(item.get("code") or 0) == 11000 for item in write_errors
        ):
            # Concurrent $setOnInsert upserts can race on a unique key. Once
            # the winner commits, replaying the same batch becomes a no-op.
            return True
        return _operation_details_are_retryable(details)
    if isinstance(error, OperationFailure):
        return _operation_failure_is_retryable(error)
    return False


async def retry_persistence(
    operation: Callable[[], Awaitable[T]],
    *,
    stage: str,
    context: dict[str, Any] | None = None,
    policy: PersistenceRetryPolicy = DEFAULT_PERSISTENCE_RETRY_POLICY,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    """Run an idempotent persistence operation with bounded backoff."""

    attempts = max(1, int(policy.max_attempts))
    delay = max(0.0, float(policy.initial_delay_seconds))
    log_context = {"event": "dsh.persistence.retry", "stage": stage, **(context or {})}
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            retryable = is_retryable_persistence_error(error)
            if not retryable or attempt >= attempts:
                logger.error(
                    "DSH persistence operation failed",
                    extra={
                        **log_context,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "retryable": retryable,
                        "error_type": type(error).__name__,
                        "error": str(error)[:500],
                    },
                    exc_info=True,
                )
                raise
            logger.warning(
                "retrying transient DSH persistence failure",
                extra={
                    **log_context,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "retry_in_ms": round(delay * 1000),
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                },
            )
            await sleep(delay)
            delay = min(max(delay * 2, 0.001), max(delay, policy.max_delay_seconds))
    raise AssertionError("unreachable persistence retry state")


def _operation_failure_is_retryable(error: OperationFailure) -> bool:
    try:
        if error.has_error_label("RetryableWriteError"):
            return True
    except (AttributeError, TypeError):
        pass
    if int(error.code or 0) in _RETRYABLE_OPERATION_CODES:
        return True
    return _operation_details_are_retryable(error.details or {})


def _operation_details_are_retryable(details: dict[str, Any]) -> bool:
    labels = details.get("errorLabels") or []
    if "RetryableWriteError" in labels:
        return True
    code = int(details.get("code") or 0)
    if code in _RETRYABLE_OPERATION_CODES:
        return True
    write_concern_errors = details.get("writeConcernErrors") or []
    return any(
        int(item.get("code") or 0) in _RETRYABLE_OPERATION_CODES
        for item in write_concern_errors
    )
