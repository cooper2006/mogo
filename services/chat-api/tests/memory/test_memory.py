"""Tests for three-scope memory core (feature 017): scope / visibility / lifecycle.

D4 target state: ``personal`` / ``project`` / ``department``. Every visibility
decision goes through a server-built ``MemoryViewerContext`` supplied as
``viewer=``; the old scattered identity kwargs are gone with no compat layer.
"""

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
    DEPARTMENT_PROMOTION_ROLES,
    Memory,
    MemoryAccessError,
    MemoryScope,
    can_promote_to_department,
    promote_to_department,
    resolve_default_scope,
    visible_to,
)
from app.memory.viewer import FULL_ACCESS_ROLE_KEY, MemoryViewerContext

TENANT = "t1"


def _viewer(
    user_id: str = "u1",
    *,
    tenant_id: str = TENANT,
    role_keys=(),
    project_keys=(),
    department_ids=(),
) -> MemoryViewerContext:
    return MemoryViewerContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(role_keys),
        visible_project_keys=frozenset(project_keys),
        visible_department_ids=frozenset(department_ids),
    )


# --- scope / default ---------------------------------------------------------


def test_default_scope_single_user_is_personal() -> None:
    assert resolve_default_scope(multi_user_session=False) == MemoryScope.PERSONAL.value


def test_default_scope_multi_user_without_project_is_personal() -> None:
    """D2/N2: co-presence alone never promotes a memory to ``project``."""
    assert resolve_default_scope(multi_user_session=True) == MemoryScope.PERSONAL.value
    assert (
        resolve_default_scope(multi_user_session=True, has_project_context=False)
        == MemoryScope.PERSONAL.value
    )


def test_default_scope_with_project_context_is_project() -> None:
    assert resolve_default_scope(has_project_context=True) == MemoryScope.PROJECT.value
    assert (
        resolve_default_scope(multi_user_session=False, has_project_context=True)
        == MemoryScope.PROJECT.value
    )


def test_memory_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError):
        Memory(scope="galaxy")


# --- visibility --------------------------------------------------------------


def test_personal_visible_only_to_owner() -> None:
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    assert visible_to(memory, viewer=_viewer("u1")) is True
    assert visible_to(memory, viewer=_viewer("u2")) is False


def test_project_visible_to_member_of_matching_project_key() -> None:
    memory = Memory(
        scope="project",
        owner_id="u1",
        tenant_id=TENANT,
        project_id="p1",
        project_owner_id="ownerA",
    )
    member = _viewer("u2", project_keys=[("p1", "ownerA")])
    outsider = _viewer("u3", project_keys=[("p1", "ownerB")])
    assert visible_to(memory, viewer=member) is True
    assert visible_to(memory, viewer=outsider) is False


def test_department_visible_to_member_of_own_department() -> None:
    memory = Memory(scope="department", owner_id="u1", tenant_id=TENANT, department_id="d1")
    assert visible_to(memory, viewer=_viewer("u9", department_ids={"d1"})) is True
    assert visible_to(memory, viewer=_viewer("u9", department_ids={"d2"})) is False


def test_department_memory_without_department_id_is_invisible() -> None:
    """Fail closed: a department memory with no department_id reads as nobody's."""
    memory = Memory(scope="department", owner_id="u1", tenant_id=TENANT)
    assert visible_to(memory, viewer=_viewer("u9", department_ids={"d1"})) is False
    assert visible_to(memory, viewer=_viewer("u9")) is False


def test_full_access_admin_sees_every_valid_scope_in_own_tenant() -> None:
    admin = _viewer("admin", role_keys=(FULL_ACCESS_ROLE_KEY,))
    memories = [
        Memory(scope="personal", owner_id="someone", tenant_id=TENANT),
        Memory(
            scope="project", owner_id="someone", tenant_id=TENANT,
            project_id="p1", project_owner_id="ownerA",
        ),
        Memory(scope="department", owner_id="someone", tenant_id=TENANT, department_id="d1"),
    ]
    for memory in memories:
        assert visible_to(memory, viewer=admin) is True


def test_full_access_admin_still_fails_closed_on_invalid_records() -> None:
    """Admin widens scope only inside its own tenant, for valid, live records."""
    admin = _viewer("admin", role_keys=(FULL_ACCESS_ROLE_KEY,))
    assert visible_to(
        Memory(scope="personal", owner_id="x", tenant_id="t2"), viewer=admin
    ) is False
    assert visible_to(
        Memory(scope="personal", owner_id="x", tenant_id=TENANT, archived=True),
        viewer=admin,
    ) is False
    # ``Memory`` rejects unknown scopes at construction, so use a raw row.
    assert visible_to({"scope": "galaxy", "tenant_id": TENANT}, viewer=admin) is False


# --- promotion ---------------------------------------------------------------


def test_only_full_access_admin_can_promote() -> None:
    assert can_promote_to_department(_viewer(role_keys=(FULL_ACCESS_ROLE_KEY,))) is True
    assert can_promote_to_department(_viewer()) is False
    assert DEPARTMENT_PROMOTION_ROLES == frozenset({FULL_ACCESS_ROLE_KEY})


def test_promote_to_department_requires_authorized_role() -> None:
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    with pytest.raises(MemoryAccessError):
        promote_to_department(memory, viewer=_viewer(), department_id="d1")


def test_promote_to_department_succeeds_for_admin() -> None:
    viewer = _viewer(role_keys=(FULL_ACCESS_ROLE_KEY,), department_ids={"d1"})
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    promoted = promote_to_department(memory, viewer=viewer, department_id="d1")
    assert promoted.scope == MemoryScope.DEPARTMENT.value
    assert promoted.department_id == "d1"
    assert promoted.visibility() == "department_subtree"


def test_promote_to_department_rejects_invisible_target() -> None:
    """G-2: even an admin cannot inject a memory into an unrelated department."""
    viewer = _viewer(role_keys=(FULL_ACCESS_ROLE_KEY,), department_ids={"d1"})
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    with pytest.raises(MemoryAccessError):
        promote_to_department(memory, viewer=viewer, department_id="d2")


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
    live = _Mem(
        content="live", scope="department", owner_id="u1", memory_id="m1",
        tenant_id=TENANT, department_id="d1",
    )
    gone = _Mem(
        content="archived", scope="department", owner_id="u2", memory_id="m2",
        tenant_id=TENANT, department_id="d1", archived=True,
    )
    survivors = scope_filter(
        [live, gone], viewer=_viewer("viewer", department_ids={"d1"})
    )
    assert [m.memory_id for m in survivors] == ["m1"]
