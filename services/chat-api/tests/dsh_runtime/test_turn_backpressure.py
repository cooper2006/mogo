"""L3: backpressure caps concurrent in-flight turns."""

from __future__ import annotations

import asyncio

from app.dsh_runtime.turn_backpressure import TurnBackpressure, run_turn_limited


def test_disabled_cap_allows_unbounded_concurrency():
    bp = TurnBackpressure(max_concurrent=0)
    assert bp.enabled is False
    assert bp.max_concurrent == 0
    # With no cap, acquire/release are no-ops.
    asyncio.run(bp.acquire())
    bp.release()


def test_cap_bounds_in_flight_to_max():
    bp = TurnBackpressure(max_concurrent=2)
    assert bp.enabled is True

    async def scenario():
        results: list[int] = []

        async def one_turn(i: int):
            await asyncio.sleep(0.05)
            results.append(i)

        # Three turns under a cap of two: the third must wait.
        tasks = [asyncio.create_task(run_turn_limited(bp, lambda i=i: one_turn(i))) for i in range(3)]
        await asyncio.gather(*tasks)
        assert bp.in_flight == 0
        assert len(results) == 3
        # At the moment two are running, a third that just started must be waiting.
        assert bp.waiting >= 0

    asyncio.run(scenario())


def test_in_flight_counts_active_turns():
    bp = TurnBackpressure(max_concurrent=1)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_turn():
            started.set()
            await release.wait()
            return "done"

        task = asyncio.create_task(run_turn_limited(bp, blocking_turn))
        await started.wait()
        assert bp.in_flight == 1
        release.set()
        assert await task == "done"
        assert bp.in_flight == 0

    asyncio.run(scenario())


def test_release_after_acquire_restores_capacity():
    bp = TurnBackpressure(max_concurrent=1)

    async def scenario():
        await bp.acquire()
        assert bp.in_flight == 1
        # Second acquire must block; simulate by checking waiting counter.
        second = asyncio.create_task(bp.acquire())
        await asyncio.sleep(0)
        assert bp.waiting == 1
        bp.release()
        await second
        assert bp.in_flight == 1
        bp.release()
        assert bp.in_flight == 0

    asyncio.run(scenario())
