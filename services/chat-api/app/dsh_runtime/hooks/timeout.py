"""Hook timeout guard with fail-closed semantics (009 FR-3 / clarify OQ-1 / OQ-2).

Default timeout is 5s (``hook_timeout_seconds`` configurable). A hook that times
out, raises, or fails to parse its rules results in **fail-closed**: the call is
rejected. This is not configurable to fail-open (constitution principle III).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, TypeVar

T = TypeVar("T")

DEFAULT_HOOK_TIMEOUT_SECONDS = 5.0


class HookTimeout(Exception):
    """Raised when a hook exceeds its timeout; callers must deny (fail-closed)."""


async def run_with_timeout(
    operation: Awaitable[T],
    *,
    timeout_seconds: float = DEFAULT_HOOK_TIMEOUT_SECONDS,
) -> T:
    """Await ``operation`` under a timeout, raising ``HookTimeout`` on expiry.

    The caller treats ``HookTimeout`` (like any hook exception) as a deny.
    """
    budget = float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else DEFAULT_HOOK_TIMEOUT_SECONDS
    try:
        return await asyncio.wait_for(operation, timeout=budget)
    except asyncio.TimeoutError as error:
        raise HookTimeout(f"hook exceeded {budget}s timeout") from error


def total_latency_budget_exceeded(
    elapsed_seconds: float,
    *,
    budget_seconds: float = DEFAULT_HOOK_TIMEOUT_SECONDS,
) -> bool:
    """Whether the stacked hooks exceeded the shared latency budget (FR-13).

    Multiple hooks share one 5s budget; exceeding it fails closed rather than
    stacking timeouts.
    """
    return elapsed_seconds > budget_seconds
