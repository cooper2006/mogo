import asyncio

from app.dsh_runtime.credential_lease import ActiveTurnCredentialLease


class _Refresher:
    """Refresher double that publishes a signal once a second call happens.

    The signal exists so the tests can *wait for* the tick they assert on
    instead of guessing how long a tick takes. Waiting on a wall-clock
    window (`await asyncio.sleep(0.13)`) left only ~28ms of margin over the
    nominal 2nd tick at 100ms, which is well inside the jitter range of
    `logger.exception` traceback formatting plus suite-wide load — the
    assertion then failed roughly 1 run in 20 without any behaviour change.
    """

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[str] = []
        self.second_call = asyncio.Event()

    async def refresh_session_credentials(self, session_id: str) -> None:
        self.calls.append(session_id)
        if len(self.calls) >= 2:
            self.second_call.set()
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transient")


def test_active_turn_credential_lease_refreshes_until_stopped() -> None:
    async def run() -> None:
        refresher = _Refresher()
        lease = ActiveTurnCredentialLease(
            refresher, session_id="session-a", interval_seconds=0.05
        )
        lease.start()
        try:
            await asyncio.wait_for(refresher.second_call.wait(), timeout=5)
        finally:
            await lease.stop()
        count = len(refresher.calls)
        await asyncio.sleep(0.07)
        assert count >= 2
        assert refresher.calls == ["session-a"] * count

    asyncio.run(run())


def test_transient_refresh_failure_does_not_end_the_lease() -> None:
    async def run() -> None:
        refresher = _Refresher(failures=1)
        lease = ActiveTurnCredentialLease(
            refresher, session_id="session-b", interval_seconds=0.05
        )
        lease.start()
        try:
            # The first tick raises; reaching a second call is exactly the
            # behaviour under test, so wait for it instead of a fixed delay.
            await asyncio.wait_for(refresher.second_call.wait(), timeout=5)
        finally:
            await lease.stop()
        assert len(refresher.calls) >= 2
        assert refresher.calls == ["session-b"] * len(refresher.calls)

    asyncio.run(run())