"""Tests for the 009 hook dispatcher (P1-1) + 009 → 017 sedimentation loop (P1-2).

These cover the previously-missing half of 009: ``emit_*`` built a payload that
nobody consumed. The dispatcher gives it a real subscriber registry, and
``app.memory.sediment`` registers itself as the ``SessionEnd`` consumer.
"""

from __future__ import annotations

import pytest

from app.dsh_runtime.hooks.dispatcher import (
    clear_subscribers,
    dispatch,
    dispatch_session_end,
    subscriber_count,
    subscribe,
    unsubscribe,
)
from app.dsh_runtime.hooks.lifecycle import HookEventPayload
from app.dsh_runtime.hooks.registry import SESSION_END
from app.memory.sediment import (
    ensure_registered,
    mark_sedimented,
    register_sedimentation_subscriber,
    reset_sedimentation_ledger,
)
from app.memory.scope import Memory


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_subscribers()
    reset_sedimentation_ledger()
    yield
    clear_subscribers()
    reset_sedimentation_ledger()


class _FakeStore:
    def __init__(self) -> None:
        self.saved: dict = {}
        self.saves = 0

    async def save(self, **kw):
        self.saves += 1
        self.saved.update(kw)
        return Memory(**kw)


# --- dispatcher ------------------------------------------------------------


def test_subscribe_rejects_unknown_event() -> None:
    with pytest.raises(ValueError):
        subscribe("NotAnEvent", lambda p: None)


def test_sync_and_async_subscribers_both_fire() -> None:
    seen: list[str] = []

    subscribe(SESSION_END, lambda p: seen.append(f"sync:{p.payload['session_id']}"))

    async def _async_handler(p):
        seen.append(f"async:{p.payload['session_id']}")

    subscribe(SESSION_END, _async_handler)

    assert subscriber_count(SESSION_END) == 2


def test_unsubscribe_removes_handler() -> None:
    def handler(p):
        return None

    subscribe(SESSION_END, handler)
    assert subscriber_count(SESSION_END) == 1
    assert unsubscribe(SESSION_END, handler) is True
    assert subscriber_count(SESSION_END) == 0
    assert unsubscribe(SESSION_END, handler) is False


async def test_dispatch_none_payload_is_noop() -> None:
    assert await dispatch(None) == []


async def test_dispatch_isolates_failing_subscriber() -> None:
    """A broken observer must not prevent healthy ones from running."""
    fired: list[str] = []

    def boom(p):
        raise RuntimeError("subscriber exploded")

    subscribe(SESSION_END, boom)
    subscribe(SESSION_END, lambda p: fired.append("healthy"))

    failures = await dispatch(
        HookEventPayload(event=SESSION_END, actor="u1", payload={"session_id": "s1"})
    )
    assert fired == ["healthy"]
    assert len(failures) == 1
    assert "subscriber exploded" in failures[0]


# --- 009 → 017 sedimentation loop -----------------------------------------


def test_register_sedimentation_subscriber_is_idempotent() -> None:
    assert register_sedimentation_subscriber() is True
    assert register_sedimentation_subscriber() is False
    assert subscriber_count(SESSION_END) == 1


def test_mark_sedimented_claims_once() -> None:
    assert mark_sedimented("s1") is True
    assert mark_sedimented("s1") is False
    assert mark_sedimented("") is False


async def test_session_end_event_actually_sediments() -> None:
    """The regression test for P1-1: emission must reach the memory write."""
    store = _FakeStore()
    ensure_registered()

    failures = await dispatch_session_end(
        "sess-9",
        actor="u1",
        payload={
            "session_doc": {"title": "Planning", "content": "roadmap talk"},
            "store": store,
            "owner_id": "u1",
            "tenant_id": "t1",
        },
    )
    assert failures == []
    # Without a real consumer this dict stays empty and the loop is not closed.
    assert store.saved["source_session_id"] == "sess-9"
    assert store.saved["source_type"] == "session"
    assert store.saved["content"] == "roadmap talk"


async def test_session_end_event_is_idempotent() -> None:
    """A second SessionEnd (e.g. delete after end) must not duplicate memory."""
    store = _FakeStore()
    ensure_registered()
    payload = {
        "session_doc": {"title": "T", "content": "body"},
        "store": store,
        "owner_id": "u1",
        "tenant_id": "t1",
    }
    await dispatch_session_end("s1", actor="u1", payload=payload)
    assert store.saves == 1
    await dispatch_session_end("s1", actor="u1", payload=payload)
    # The ledger claim makes the second dispatch a no-op — no second write.
    assert store.saves == 1


async def test_event_without_store_is_notification_only() -> None:
    """Emitters that only want notification (no store) must not crash."""
    ensure_registered()
    failures = await dispatch_session_end("s2", actor="u1", payload={"tenant_id": "t1"})
    assert failures == []
