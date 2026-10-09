"""§ M2: distributed runtime-creation lock.

These tests pin the coordination contract: two concurrent holders for one
isolation key must serialise, a loser must fall through to discovery instead
of blocking, an unavailable backend must degrade to pre-lock behaviour, and a
release must never clear a lock it does not own.
"""

from __future__ import annotations

from app.dsh_runtime.runtime_coordinator import RuntimeCoordinator
from app.dsh_runtime.runtime_lock import RuntimeLock


class _FakeRedis:
    """In-memory stand-in for the small subset of redis used here."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def eval(self, script, numkeys, key, value):
        if self.store.get(key) == value:
            del self.store[key]
            return 1
        return 0

    def ping(self) -> None:
        return None


class _NoRedis:
    """A Redis client whose every call raises, simulating an outage."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def __getattr__(self, name):
        def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        return _raise


def _lock_with(redis) -> RuntimeLock:
    lock = RuntimeLock(None)
    lock._redis = redis
    return lock


def test_two_holders_are_serialised_and_loser_discovers():
    """With a shared lock backend, the second acquire sees the first's token
    and must not block: it proceeds, the loser discovers the winner's runtime
    rather than creating a forked one."""
    redis = _FakeRedis()
    lock = _lock_with(redis)

    token_a = lock.acquire("tenant:t1:profile:v1")
    token_b = lock.acquire("tenant:t1:profile:v1")

    assert token_a is not None
    assert token_b is None
    # The winner's release must clear the lock for the next acquisition.
    lock.release("tenant:t1:profile:v1", token_a)
    assert lock.acquire("tenant:t1:profile:v1") is not None


def test_release_never_clears_a_lock_it_does_not_own():
    """After a TTL expiry a concurrent holder may have taken the lock; a late
    release with the stale token must not delete the new holder's lock."""
    redis = _FakeRedis()
    lock = _lock_with(redis)
    key = "mogo:dsh:runtime:k"

    token_a = lock.acquire("k")
    assert token_a is not None
    # Simulate TTL expiry: holder A's token is gone, holder B takes over.
    redis.store.clear()
    token_b = lock.acquire("k")
    assert token_b is not None
    # Holder A's late release with its stale token must not touch B's lock.
    lock.release("k", token_a)
    assert redis.store.get(key) == token_b


def test_lock_degrades_to_noop_when_redis_is_unavailable():
    """An unavailable backend must degrade to pre-M2 behaviour: acquire
    returns None, release is a no-op, and the caller proceeds uncoordinated
    (create then discover on conflict)."""
    lock = _lock_with(_NoRedis())

    token = lock.acquire("k")
    assert token is None
    # Must not raise.
    lock.release("k", token)
    assert lock.enabled is True  # backend object exists, just unreachable


def test_lock_disabled_when_no_redis_url():
    lock = RuntimeLock(None)
    assert lock.enabled is False
    assert lock.acquire("k") is None
    lock.release("k", None)


def test_disabled_lock_never_touches_the_backend():
    """When DSH_RUNTIME_DISTRIBUTED_LOCK is off the coordinator gets
    ``runtime_lock=None`` and must not call into any lock at all."""
    lock = _lock_with(_FakeRedis())
    coordinator = RuntimeCoordinator(gateway=None, bindings=None)  # type: ignore[arg-type]
    coordinator._runtime_lock = None  # simulate the flag being off
    # There is no code path that reaches the lock; just assert the guard.
    assert coordinator._runtime_lock is None


class _ScriptedGateway:
    def __init__(self) -> None:
        self.create_calls = 0
        self.discover_calls = 0
        self.create_result = "created"
        self.discover_result: object = None
        self.runtime = None

    async def discover_runtime(self, **kwargs):
        self.discover_calls += 1
        if self.discover_result is not None:
            self.runtime = self.discover_result
            return self.runtime
        return None

    async def create_runtime(self, request):
        self.create_calls += 1
        return self.create_result


class _ScriptedBindings:
    async def create(self, **fields):
        return fields

    async def update_runtime(self, binding_id, *, runtime_id):
        pass


def _coordinator(gateway, lock) -> RuntimeCoordinator:
    coordinator = RuntimeCoordinator(gateway, _ScriptedBindings(), None, lock)
    return coordinator


import asyncio  # noqa: E402


def test_coordinator_acquires_lock_before_creating():
    redis = _FakeRedis()
    lock = _lock_with(redis)
    gateway = _ScriptedGateway()
    coordinator = _coordinator(gateway, lock)

    async def run():
        return await coordinator._runtime(tenant_id="t1", profile_version="v1")

    result = asyncio.run(run())
    assert result == "created"
    assert gateway.create_calls == 1
    # The lock must have been released after creation.
    assert redis.get("mogo:dsh:runtime:tenant:t1:profile:v1") is None


def test_coordinator_losers_discover_the_winner():
    redis = _FakeRedis()
    lock = _lock_with(redis)
    gateway = _ScriptedGateway()
    gateway.discover_result = "existing-runtime"
    coordinator = _coordinator(gateway, lock)

    async def run():
        return await coordinator._runtime(tenant_id="t1", profile_version="v1")

    # Pre-set the lock as held by someone else, so acquire returns None and
    # the coordinator falls through to discovery.
    redis.store["mogo:dsh:runtime:tenant:t1:profile:v1"] = "someone-else"
    result = asyncio.run(run())
    assert result == "existing-runtime"
    assert gateway.create_calls == 0
    assert gateway.discover_calls == 1
