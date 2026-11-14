"""T035 promotion approval state machine + T037 offboarding unit tests (017).

Pure-logic coverage for ``app.memory.promotion`` and ``app.memory.offboarding``
plus the fail-closed invalidation in ``scope.visible_to``. No live DB: the
admin-side invalidation functions take an injected ``db`` so they are exercised
with an in-memory fake.
"""

from __future__ import annotations

import pytest

from app.memory import promotion as promotion_sm
from app.memory.offboarding import (
    invalidate_project_memories,
    invalidate_user_memories,
    restore_user_memories,
)
from app.memory.scope import (
    Memory,
    MemoryScope,
    PROMOTION_STATUS_APPROVED,
    PROMOTION_STATUS_NONE,
    PROMOTION_STATUS_PENDING,
    PROMOTION_STATUS_REJECTED,
    visible_to,
)
from app.memory.viewer import MemoryViewerContext


# ── viewer builders ───────────────────────────────────────────────────────
def _owner(visible_departments=("d1",), primary="d1"):
    return MemoryViewerContext(
        tenant_id="t1",
        user_id="u1",
        visible_department_ids=frozenset(visible_departments),
        primary_department_id=primary,
    )


def _admin(visible_departments=("d1",)):
    return MemoryViewerContext(
        tenant_id="t1",
        user_id="admin",
        role_keys=frozenset({"full_access_admin"}),
        visible_department_ids=frozenset(visible_departments),
        primary_department_id="d1",
    )


def _personal(owner="u1", **kw):
    return Memory(memory_id="m1", content="c", scope="personal", owner_id=owner,
                  tenant_id="t1", **kw)


# ── T035 transitions ──────────────────────────────────────────────────────
def test_request_from_none_moves_to_pending():
    m = _personal()
    v = _owner()
    promotion_sm.request_promotion(m, viewer=v, department_id="d1", reason="want dept")
    assert m.promotion_status == PROMOTION_STATUS_PENDING
    assert m.pending_department_id == "d1"
    assert m.promotion_requested_by == "u1"
    assert m.promotion_reason == "want dept"
    assert m.promotion_requested_at > 0


def test_request_requires_owner():
    m = _personal(owner="u2")  # not the caller
    v = _owner()
    with pytest.raises(Exception):  # MemoryAccessError
        promotion_sm.request_promotion(m, viewer=v, department_id="d1")


def test_request_rejected_target_department_not_visible():
    m = _personal()
    v = _owner(visible_departments=("d1",))
    with pytest.raises(Exception):
        # d9 is not in the viewer's visible department set
        promotion_sm.request_promotion(m, viewer=v, department_id="d9")


def test_approve_pending_promotes_to_department():
    m = _personal()
    m.promotion_status = PROMOTION_STATUS_PENDING
    m.pending_department_id = "d1"
    admin = _admin()
    promotion_sm.approve_promotion(m, viewer=admin, department_id="d1")
    assert m.scope == MemoryScope.DEPARTMENT.value
    assert m.department_id == "d1"
    assert m.promotion_status == PROMOTION_STATUS_APPROVED
    assert m.promotion_resolved_by == "admin"


def test_reject_pending_keeps_scope():
    m = _personal()
    m.promotion_status = PROMOTION_STATUS_PENDING
    m.pending_department_id = "d1"
    admin = _admin()
    promotion_sm.reject_promotion(m, viewer=admin, reason="nope")
    assert m.promotion_status == PROMOTION_STATUS_REJECTED
    assert m.scope == MemoryScope.PERSONAL.value  # scope unchanged
    assert m.promotion_resolved_by == "admin"


def test_approve_when_not_pending_fails():
    m = _personal()  # status none
    admin = _admin()
    with pytest.raises(Exception):
        promotion_sm.approve_promotion(m, viewer=admin, department_id="d1")


def test_reject_when_not_pending_fails():
    m = _personal()
    admin = _admin()
    with pytest.raises(Exception):
        promotion_sm.reject_promotion(m, viewer=admin)


def test_rejected_can_be_reequsted():
    m = _personal()
    m.promotion_status = PROMOTION_STATUS_REJECTED
    v = _owner()
    promotion_sm.request_promotion(m, viewer=v, department_id="d1")
    assert m.promotion_status == PROMOTION_STATUS_PENDING


# ── T037 invalidation is fail-closed in visible_to ───────────────────────
def test_invalidated_memory_invisible_to_normal_viewer():
    m = _personal(invalidated=True, invalidated_reason="owner_offboarded")
    v = _owner()
    assert visible_to(m, v) is False


def test_invalidated_still_invisible_even_if_admin():
    # visible_to is the *normal* path; admin governance uses _governance_visible
    # which intentionally still lists invalidated records for audit. Here we only
    # assert the normal path hides them regardless of role.
    m = _personal(invalidated=True)
    admin = _admin()
    assert visible_to(m, admin) is False


# ── T037 offboarding service (injected fake db) ──────────────────────────
class _FakeResult:
    def __init__(self, modified):
        self.modified_count = modified


class _FakeCollection:
    def __init__(self, rows):
        self._rows = rows

    async def update_many(self, query, update):
        set_fields = update.get("$set", {})
        modified = 0
        for row in self._rows:
            ok = True
            for k, val in query.items():
                if k == "$or":
                    if not any(
                        all(row.get(fk) == fv for fk, fv in clause.items())
                        for clause in val
                    ):
                        ok = False
                        break
                    continue
                if isinstance(val, dict) and "$ne" in val:
                    # keep rows where field != value; skip when equal
                    if row.get(k) == val["$ne"]:
                        ok = False
                        break
                else:
                    if row.get(k) != val:
                        ok = False
                        break
            if ok:
                row.update(set_fields)
                modified += 1
        return _FakeResult(modified)


class _FakeDB:
    def __init__(self, rows):
        self.memories = _FakeCollection(rows)

    def __getitem__(self, name):
        return self.memories


def test_invalidate_user_memories_offboards_owner_personal_and_project():
    rows = [
        {"tenant_id": "t1", "scope": "personal", "owner_id": "u1", "project_owner_id": "", "archived": False, "invalidated": False},
        {"tenant_id": "t1", "scope": "project", "owner_id": "x", "project_owner_id": "u1", "archived": False, "invalidated": False},
        # member-only project memory (not owner) must NOT be invalidated
        {"tenant_id": "t1", "scope": "project", "owner_id": "u1", "project_owner_id": "other", "archived": False, "invalidated": False},
        # already archived -> skipped
        {"tenant_id": "t1", "scope": "personal", "owner_id": "u1", "project_owner_id": "", "archived": True, "invalidated": False},
    ]
    db = _FakeDB(rows)
    count = await_if_needed(invalidate_user_memories("t1", "u1", reason="left", db=db))
    assert count == 2
    assert rows[0]["invalidated"] is True and rows[0]["invalidated_reason"] == "left"
    assert rows[1]["invalidated"] is True
    assert rows[2]["invalidated"] is False  # member-only untouched
    assert rows[3]["invalidated"] is False  # archived untouched


def test_invalidate_user_memories_noop_without_db(monkeypatch):
    # get_db() is unusable in this env (no real Mongo) → function must no-op safely.
    import app.memory.offboarding as offboarding_mod

    monkeypatch.setattr(offboarding_mod, "get_db", lambda: None)
    assert await_if_needed(invalidate_user_memories("t1", "u1")) == 0


def test_invalidate_project_memories_marks_owned_project():
    rows = [
        {"tenant_id": "t1", "scope": "project", "project_id": "p1", "project_owner_id": "ownerA", "archived": False, "invalidated": False},
        {"tenant_id": "t1", "scope": "project", "project_id": "p1", "project_owner_id": "ownerB", "archived": False, "invalidated": False},
    ]
    db = _FakeDB(rows)
    count = await_if_needed(invalidate_project_memories("t1", "p1", "ownerA", db=db))
    assert count == 1
    assert rows[0]["invalidated"] is True
    assert rows[1]["invalidated"] is False  # different owner untouched


def test_restore_user_memories_reverts_offboarding():
    rows = [
        {"tenant_id": "t1", "scope": "personal", "owner_id": "u1", "invalidated": True, "invalidated_reason": "owner_offboarded"},
        {"tenant_id": "t1", "scope": "personal", "owner_id": "u1", "invalidated": True, "invalidated_reason": "other"},
    ]
    db = _FakeDB(rows)
    count = await_if_needed(restore_user_memories("t1", "u1", db=db))
    assert count == 1
    assert rows[0]["invalidated"] is False
    assert rows[1]["invalidated"] is True  # different reason untouched


def await_if_needed(coro):
    """Run a coroutine if one was returned (keeps the test file importable without
    pytest-asyncio surprises in plain functions)."""
    import asyncio
    import inspect

    if inspect.isawaitable(coro):
        return asyncio.run(coro)
    return coro
