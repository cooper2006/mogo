"""L3 backpressure: bound the number of in-flight DSH turns per chat-api.

Every multi-replica copy of chat-api forwards its turns to the pool, so the
LLM gateway's load scales with the replica count. A process-level semaphore
caps how many turns one chat-api may have in flight at once; when the cap is
reached, additional turns queue (FIFO) instead of piling onto the upstream.

The cap is set by DSH_RUNTIME_TURN_MAX_CONCURRENT; 0 disables the cap
(legacy behaviour). The default of 32 matches a single chat-api process and
is the value the plan recommends for the 3-replica topology.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class TurnBackpressure:
    """FIFO admission gate for in-flight turns.

    The cap is held for the entire turn (send + stream + finalize) via
    :func:`run_turn_limited`, so a slow turn blocks its slot rather than
    the slot being released after the send call.
    """

    def __init__(self, max_concurrent: int = 32) -> None:
        self._max = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None if max_concurrent <= 0 else asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._waiting = 0

    @property
    def enabled(self) -> bool:
        return self._semaphore is not None

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def waiting(self) -> int:
        return self._waiting

    async def acquire(self) -> None:
        if self._semaphore is None:
            return
        self._waiting += 1
        try:
            await self._semaphore.acquire()
        finally:
            self._waiting -= 1
        self._in_flight += 1

    def release(self) -> None:
        if self._semaphore is None:
            return
        self._in_flight -= 1
        self._semaphore.release()


async def run_turn_limited(backpressure: TurnBackpressure, run_coro_factory):
    """Run one turn under the backpressure cap.

    ``run_coro_factory`` is a zero-arg callable returning the turn's
    coroutine. The cap is held for the whole turn, so a slow turn blocks
    its slot, not just the send call.
    """
    await backpressure.acquire()
    try:
        return await run_coro_factory()
    finally:
        backpressure.release()
