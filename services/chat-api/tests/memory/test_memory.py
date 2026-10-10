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


def test_org_visible_to_member_of_own_org() -> None:
    """R-04: an org-scoped memory is visible only to members of the organization
    that owns it — not to any authenticated user in the tenant."""
    memory = Memory(scope="org", org_id="org1")
    assert visible_to(memory, viewer_id="u9", viewer_org_id="org1") is True
    assert visible_to(memory, viewer_id="u9", viewer_org_id="org2") is False


def test_org_memory_without_org_id_is_invisible() -> None:
    """Safe fail-closed: an org-scoped memory that was never tagged with an
    org_id (legacy data, or written before the R-04 fix) is invisible to
    everyone — including full-access admins, who are handled earlier in
    visible_to but still require a real org_id for the org branch."""
    memory = Memory(scope="org")
    assert visible_to(memory, viewer_id="u9", viewer_org_id="org1") is False
    assert visible_to(memory, viewer_id="u9", viewer_org_id="") is False


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


# --- 017 FR-8 残项：老化清理 ------------------------------------------------

from app.memory.lifecycle import build_cleanup_query, clean_decayed_memories
from app.memory.scope import Memory as _Mem


class _FakeColl:
    def __init__(self, rows):
        self._rows = [dict(r) for r in rows]
        self.deleted = []
        self.modified_count = 0

    def find(self, query):
        cutoff = query["last_accessed_at"]["$lt"]
        return [dict(r) for r in self._rows if r.get("last_accessed_at", 0) < cutoff]

    def delete_many(self, query):
        cutoff = query["last_accessed_at"]["$lt"]
        keep, dropped = [], []
        for row in self._rows:
            if row.get("last_accessed_at", 0) < cutoff:
                dropped.append(row)
            else:
                keep.append(row)
        self._rows = keep
        self.deleted.extend(dropped)
        return type("R", (), {"deleted_count": len(dropped)})()

    def bulk_write(self, ops):
        n = 0
        for op in ops:
            q = op._filter
            upd = op._doc["$set"]
            for row in self._rows:
                if (row.get("memory_id") == q.get("memory_id")
                        and row.get("tenant_id", "") == q.get("tenant_id", "")
                        and not row.get("archived")):
                    row["archived"] = upd["archived"]
                    row["archived_at"] = upd["archived_at"]
                    n += 1
        self.modified_count = n
        return type("R", (), {"modified_count": n})()


class _FakeDB:
    def __init__(self, coll):
        self._coll = coll

    def __getitem__(self, name):
        assert name == "memories"
        return self._coll


def test_build_cleanup_query_cutoff_and_tenant() -> None:
    now = 1_000_000.0
    q = build_cleanup_query(now=now)
    assert q["last_accessed_at"]["$lt"] == now - 30 * SECONDS_PER_DAY
    assert "tenant_id" not in q
    q2 = build_cleanup_query(now=now, tenant_id="main-1")
    assert q2["tenant_id"] == "main-1"
    short = MemoryLifecycle(decay_days=1)
    q3 = build_cleanup_query(now=now, lifecycle=short)
    assert q3["last_accessed_at"]["$lt"] == now - SECONDS_PER_DAY


def test_clean_decayed_archives_by_default() -> None:
    """Archival stamps the expired docs and returns the count; fresh docs
    are untouched."""
    # 1-day decay policy → cutoff = now - 86400.
    # m-old: last_accessed_at = 0 (expired, below cutoff)
    # m-fresh: last_accessed_at = now (not expired, above cutoff)
    now = 1_000_000.0
    lifecycle = MemoryLifecycle(decay_days=1)  # 1-day decay for the test
    coll = _FakeColl([
        {"memory_id": "m-old", "tenant_id": "main-1", "last_accessed_at": 0.0},
        {"memory_id": "m-old2", "tenant_id": "main-1", "last_accessed_at": 0.0},
        {"memory_id": "m-fresh", "tenant_id": "main-1", "last_accessed_at": now},
    ])
    result = clean_decayed_memories(db=_FakeDB(coll), now=now, lifecycle=lifecycle)
    assert result == {"removed": 0, "archived": 2, "cleanup": "archive"}
    archived_ids = sorted(r["memory_id"] for r in coll._rows if r.get("archived"))
    assert archived_ids == ["m-old", "m-old2"]
    assert "archived" not in next(r for r in coll._rows if r["memory_id"] == "m-fresh")


def test_clean_decayed_delete_disposition() -> None:
    now = 1_000_000.0
    lifecycle = MemoryLifecycle(decay_days=1, cleanup="delete")
    coll = _FakeColl([
        {"memory_id": "m-old", "tenant_id": "main-1", "last_accessed_at": 0.0},
        {"memory_id": "m-fresh", "tenant_id": "main-1", "last_accessed_at": now},
    ])
    result = clean_decayed_memories(db=_FakeDB(coll), now=now, lifecycle=lifecycle)
    assert result["removed"] == 1 and result["cleanup"] == "delete"
    assert [r["memory_id"] for r in coll._rows] == ["m-fresh"]


def test_scope_filter_excludes_archived_memories() -> None:
    from app.memory.retrieval import scope_filter
    live = _Mem(content="live", scope="org", owner_id="u1", memory_id="m1", org_id="org1")
    gone = _Mem(content="archived", scope="org", owner_id="u2", memory_id="m2", org_id="org1")
    gone.archived = True
    survivors = scope_filter([live, gone], viewer_id="viewer", viewer_org_id="org1")
    assert [m.memory_id for m in survivors] == ["m1"]
