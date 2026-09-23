"""Tests for three-scope memory core (feature 017): scope / visibility / lifecycle."""

from __future__ import annotations

import pytest

from app.memory.lifecycle import (
    CLEANUP_ARCHIVE,
    DEFAULT_DECAY_DAYS,
    SECONDS_PER_DAY,
    MemoryLifecycle,
    is_expired,
    seconds_until_expiry,
    touch,
)
from app.memory.scope import (
    Memory,
    MemoryAccessError,
    MemoryScope,
    can_promote_to_org,
    promote_to_org,
    resolve_default_scope,
    visible_to,
)


# --- scope / default ---------------------------------------------------------

def test_default_scope_single_user_is_personal() -> None:
    assert resolve_default_scope(multi_user_session=False) == MemoryScope.PERSONAL.value


def test_default_scope_multi_user_is_workspace() -> None:
    assert resolve_default_scope(multi_user_session=True) == MemoryScope.WORKSPACE.value


def test_memory_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError):
        Memory(scope="galaxy")


# --- visibility --------------------------------------------------------------

def test_personal_visible_only_to_owner() -> None:
    memory = Memory(scope="personal", owner_id="u1")
    assert visible_to(memory, viewer_id="u1") is True
    assert visible_to(memory, viewer_id="u2") is False


def test_workspace_visible_to_members() -> None:
    memory = Memory(scope="workspace", workspace_id="w1")
    assert visible_to(memory, viewer_id="u2", is_workspace_member=True) is True
    assert visible_to(memory, viewer_id="u3", is_workspace_member=False) is False


def test_org_visible_to_any_member() -> None:
    memory = Memory(scope="org")
    assert visible_to(memory, viewer_id="u9") is True
    assert visible_to(memory, viewer_id="") is False


def test_full_access_admin_sees_every_scope() -> None:
    for scope in ("personal", "workspace", "org"):
        memory = Memory(scope=scope, owner_id="someone")
        assert visible_to(memory, viewer_id="admin", viewer_role="full_access_admin") is True


# --- promotion ---------------------------------------------------------------

def test_only_full_access_admin_can_promote() -> None:
    assert can_promote_to_org(role="full_access_admin") is True
    assert can_promote_to_org(role="member") is False


def test_promote_to_org_requires_authorized_role() -> None:
    memory = Memory(scope="personal", owner_id="u1")
    with pytest.raises(MemoryAccessError):
        promote_to_org(memory, role="member")


def test_promote_to_org_succeeds_for_admin() -> None:
    memory = Memory(scope="personal", owner_id="u1")
    promoted = promote_to_org(memory, role="full_access_admin")
    assert promoted.scope == MemoryScope.ORG.value
    assert promoted.visibility() == "organization"


# --- lifecycle ---------------------------------------------------------------

def test_default_decay_is_thirty_days() -> None:
    assert DEFAULT_DECAY_DAYS == 30
    assert MemoryLifecycle().decay_seconds == 30 * SECONDS_PER_DAY


def test_not_expired_within_window() -> None:
    now = 1_000_000.0
    assert is_expired(last_accessed_at=now - 10 * SECONDS_PER_DAY, now=now) is False


def test_expired_past_window() -> None:
    now = 1_000_000.0
    assert is_expired(last_accessed_at=now - 31 * SECONDS_PER_DAY, now=now) is True


def test_seconds_until_expiry_counts_down() -> None:
    now = 1_000_000.0
    remaining = seconds_until_expiry(last_accessed_at=now, now=now)
    assert remaining == 30 * SECONDS_PER_DAY
    assert seconds_until_expiry(last_accessed_at=now - 40 * SECONDS_PER_DAY, now=now) < 0


def test_touch_resets_timer() -> None:
    now = 1_000_000.0
    old = now - 40 * SECONDS_PER_DAY
    assert is_expired(last_accessed_at=old, now=now) is True
    assert is_expired(last_accessed_at=touch(old, now), now=now) is False


def test_cleanup_default_is_archive() -> None:
    assert MemoryLifecycle().cleanup == CLEANUP_ARCHIVE
