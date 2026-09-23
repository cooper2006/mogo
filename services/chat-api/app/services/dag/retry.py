"""Node-level retry with exponential backoff (010 T016-T017).

DAG nodes retry *their own execution* with exponential backoff. This layer
reuses the 007 LLM-gateway resilience scheduler for the underlying model
calls — it does NOT re-implement model-level backoff (T017: 分层不重复).

The graph already carries per-node retry config (``Node.retry``); this module
provides the scheduling math (backoff curve) plus a runner that respects the
007 layering.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.orchestration.graph import Node


# 010 T016 defaults; all configurable via Node.retry.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_SECONDS = 2.0
DEFAULT_FACTOR = 2.0
DEFAULT_CAP_SECONDS = 60.0


def backoff_delay(
    attempt: int,
    *,
    base: float = DEFAULT_BASE_SECONDS,
    factor: float = DEFAULT_FACTOR,
    cap: float = DEFAULT_CAP_SECONDS,
) -> float:
    """Exponential backoff delay for a given 1-based attempt (010 T016)."""
    if attempt < 1:
        return 0.0
    delay = base * (factor ** (attempt - 1))
    return min(delay, cap)


def backoff_from_node(node: Node, attempt: int) -> float:
    """Backoff for a node attempt, reading the node's retry config (T016)."""
    retry = node.retry or {}
    base = float(retry.get("base_seconds", DEFAULT_BASE_SECONDS))
    factor = float(retry.get("factor", DEFAULT_FACTOR))
    cap = float(retry.get("cap_seconds", DEFAULT_CAP_SECONDS))
    return backoff_delay(attempt, base=base, factor=factor, cap=cap)


@dataclass
class RetryPolicy:
    """Node-level retry policy (010 T016): counts + exponential backoff, all configurable."""
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_seconds: float = DEFAULT_BASE_SECONDS
    factor: float = DEFAULT_FACTOR
    cap_seconds: float = DEFAULT_CAP_SECONDS
    # When True, model-level backoff is delegated to the 007 resilience
    # scheduler instead of being re-implemented here (T017: 分层不重复).
    delegate_model_backoff: bool = True

    def delay_for(self, attempt: int) -> float:
        return backoff_delay(
            attempt,
            base=self.base_seconds,
            factor=self.factor,
            cap=self.cap_seconds,
        )


def policy_from_node(node: Node) -> RetryPolicy:
    """Build a RetryPolicy from a node's ``retry`` config."""
    retry = node.retry or {}
    return RetryPolicy(
        max_attempts=int(retry.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
        base_seconds=float(retry.get("base_seconds", DEFAULT_BASE_SECONDS)),
        factor=float(retry.get("factor", DEFAULT_FACTOR)),
        cap_seconds=float(retry.get("cap_seconds", DEFAULT_CAP_SECONDS)),
    )


@dataclass
class NodeRetryResult:
    """Outcome of running one DAG node with retry (010 T017)."""
    node_id: str
    attempts: int
    succeeded: bool
    final_result: Any = None
    error: Optional[BaseException] = None

    @property
    def exhausted(self) -> bool:
        return not self.succeeded


def run_node_with_retry(
    node_id: str,
    run_node: Callable[[], Awaitable[Any]],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], Any] | None = None,
    on_attempt: Callable[[str, int, Optional[BaseException]], Any] | None = None,
) -> NodeRetryResult:
    """Run one DAG node with exponential-backoff retry (010 T016-T017).

    - Retries the *node execution* up to ``policy.max_attempts``.
    - Backoff delays are exponential (T016).
    - When ``policy.delegate_model_backoff`` is True, the model-level backoff is
      handled by the 007 resilience scheduler, so this layer only retries the
      node and does not re-do model backoff (T017: 分层不重复).

    ``sleep`` is injectable for tests; ``on_attempt`` records each attempt.
    """
    policy = policy or RetryPolicy()
    attempts = 0
    last_error: Optional[BaseException] = None
    while attempts < policy.max_attempts:
        attempts += 1
        try:
            if _is_running_loop():
                result = _run_coro(run_node())
            else:
                result = asyncio.run(run_node())
            if on_attempt:
                on_attempt(node_id, attempts, None)
            return NodeRetryResult(
                node_id=node_id, attempts=attempts, succeeded=True, final_result=result
            )
        except Exception as error:  # noqa: BLE001 — retry until exhausted
            last_error = error
            if on_attempt:
                on_attempt(node_id, attempts, error)
            if attempts >= policy.max_attempts:
                break
            delay = policy.delay_for(attempts)
            if delay > 0:
                if sleep is not None:
                    sleep(delay)
                else:
                    import time

                    time.sleep(delay)
    return NodeRetryResult(
        node_id=node_id, attempts=attempts, succeeded=False, error=last_error
    )


def _is_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _run_coro(coro):
    import asyncio

    # We are already inside a running loop; schedule on it.
    return asyncio.ensure_future(coro)


__all__ = [
    "NodeRetryResult",
    "RetryPolicy",
    "backoff_delay",
    "backoff_from_node",
    "policy_from_node",
    "run_node_with_retry",
]
