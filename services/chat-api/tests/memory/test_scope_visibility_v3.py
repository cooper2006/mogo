"""017 v3 visibility matrix (SC-1/2/3/4/13 + B-7 + admin semantics).

D4 target state: ``personal`` / ``project`` / ``department``. Every decision
is made by ``visible_to(memory, viewer=MemoryViewerContext)``; the old
``workspace`` / ``org`` scopes, scattered identity kwargs and compat aliases
are gone. This file is the single regression net for the whole matrix.
"""

from __future__ import annotations

import pytest

from app.memory.scope import (
    DEFAULT_PROJECT_ID,
    Memory,
    MemoryAccessError,
    MemoryScope,
    promote_to_department,
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


def _admin(**kw) -> MemoryViewerContext:
    return _viewer(role_keys=(FULL_ACCESS_ROLE_KEY,), **kw)


# --- SC-1: cross tenant ------------------------------------------------------


@pytest.mark.parametrize("scope", ["personal", "project", "department"])
def test_cross_tenant_memory_is_invisible_for_every_scope(scope: str) -> None:
    memory = Memory(
        scope=scope, owner_id="u1", tenant_id="t2",
        project_id="p1", project_owner_id="ownerA", department_id="d1",
    )
    assert visible_to(memory, viewer=_viewer("u1", project_keys=[("p1", "ownerA")],
                                             department_ids={"d1"})) is False
    # Admin widening never crosses the tenant boundary.
    assert visible_to(memory, viewer=_admin()) is False


def test_cross_tenant_personal_memory_is_invisible_even_for_same_user_id() -> None:
    memory = Memory(scope="personal", owner_id="u1", tenant_id="t2")
    assert visible_to(memory, viewer=_viewer("u1")) is False


# --- SC-2 / SC-4: project membership -----------------------------------------


def test_project_memory_invisible_to_non_member() -> None:
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="p1", project_owner_id="ownerA",
    )
    assert visible_to(memory, viewer=_viewer("u2")) is False
    assert visible_to(memory, viewer=_viewer("u2", project_keys=[("p2", "ownerA")])) is False
    assert visible_to(memory, viewer=_viewer("u2", project_keys=[("p1", "ownerA")])) is True


def test_same_project_id_different_owner_are_mutually_invisible() -> None:
    """N1: projects._id is not unique within a tenant — the (id, owner) pair
    is the identity, so two owners' memories with the same project id never
    leak into each other."""
    mem_a = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="p1", project_owner_id="ownerA", memory_id="m-a",
    )
    mem_b = Memory(
        scope="project", owner_id="u2", tenant_id=TENANT,
        project_id="p1", project_owner_id="ownerB", memory_id="m-b",
    )
    viewer_a = _viewer("u1", project_keys=[("p1", "ownerA")])
    viewer_b = _viewer("u2", project_keys=[("p1", "ownerB")])
    assert visible_to(mem_a, viewer=viewer_a) is True
    assert visible_to(mem_b, viewer=viewer_a) is False
    assert visible_to(mem_b, viewer=viewer_b) is True
    assert visible_to(mem_a, viewer=viewer_b) is False


def test_project_memory_missing_project_owner_id_is_invisible() -> None:
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="p1", project_owner_id="",
    )
    assert visible_to(memory, viewer=_viewer("u1", project_keys=[("p1", "ownerA")])) is False
    assert visible_to(memory, viewer=_viewer("u2")) is False


def test_project_memory_missing_project_id_is_invisible() -> None:
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="", project_owner_id="ownerA",
    )
    assert visible_to(memory, viewer=_viewer("u1", project_keys=[("p1", "ownerA")])) is False


def test_default_project_memory_is_invisible() -> None:
    """N2: the 049 tenant-wide ``default`` row is never a memory scope target."""
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id=DEFAULT_PROJECT_ID, project_owner_id="ownerA",
    )
    assert visible_to(
        memory,
        viewer=_viewer("u1", project_keys=[(DEFAULT_PROJECT_ID, "ownerA")]),
    ) is False
    assert visible_to(memory, viewer=_viewer("u1")) is False


# --- SC-3: department hierarchy ----------------------------------------------


def test_subordinate_cannot_read_superior_department() -> None:
    """A viewer in a leaf department sees only itself + descendants, never
    ancestors or sibling branches."""
    parent_note = Memory(
        scope="department", owner_id="boss", tenant_id=TENANT, department_id="d-parent",
    )
    leaf_viewer = _viewer("intern", department_ids={"d-leaf"})
    assert visible_to(parent_note, viewer=leaf_viewer) is False


def test_superior_can_read_descendant_department() -> None:
    """A viewer whose visible set includes descendants reads their memories."""
    child_note = Memory(
        scope="department", owner_id="staff", tenant_id=TENANT, department_id="d-child",
    )
    root_viewer = _viewer(
        "boss", department_ids={"d-root", "d-child", "d-grandchild"}
    )
    assert visible_to(child_note, viewer=root_viewer) is True


def test_department_memory_missing_department_id_is_invisible() -> None:
    memory = Memory(scope="department", owner_id="u1", tenant_id=TENANT)
    assert visible_to(memory, viewer=_viewer("u1", department_ids={"d1"})) is False


# --- SC-13 / B-7: archived, unknown scope, invalid viewer --------------------


def test_archived_memory_is_invisible_for_ordinary_and_admin() -> None:
    memory = Memory(
        scope="project", owner_id="u1", tenant_id=TENANT,
        project_id="p1", project_owner_id="ownerA", archived=True,
    )
    assert visible_to(memory, viewer=_viewer("u1", project_keys=[("p1", "ownerA")])) is False
    assert visible_to(memory, viewer=_admin()) is False


@pytest.mark.parametrize("legacy_scope", ["workspace", "org", "galaxy", ""])
def test_unknown_or_legacy_scope_is_invisible(legacy_scope: str) -> None:
    """D4 has no normalize_scope / alias: retired scopes fail closed."""
    row = {
        "scope": legacy_scope,
        "tenant_id": TENANT,
        "owner_id": "u1",
        "project_id": "p1",
        "project_owner_id": "ownerA",
        "department_id": "d1",
    }
    assert visible_to(row, viewer=_viewer("u1", project_keys=[("p1", "ownerA")],
                                          department_ids={"d1"})) is False
    assert visible_to(row, viewer=_admin()) is False


def test_non_context_viewer_is_fail_closed() -> None:
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    assert visible_to(memory, viewer="u1") is False  # type: ignore[arg-type]
    assert visible_to(memory, viewer=None) is False  # type: ignore[arg-type]
    assert visible_to(memory, viewer=MemoryViewerContext()) is False


# --- admin semantics ---------------------------------------------------------


def test_admin_reads_every_valid_live_scope_in_own_tenant() -> None:
    admin = _admin()
    memories = [
        Memory(scope="personal", owner_id="someone", tenant_id=TENANT),
        Memory(
            scope="project", owner_id="someone", tenant_id=TENANT,
            project_id="p9", project_owner_id="ownerZ",
        ),
        Memory(scope="department", owner_id="someone", tenant_id=TENANT, department_id="d9"),
    ]
    for memory in memories:
        assert visible_to(memory, viewer=admin) is True


def test_admin_still_fails_closed_on_cross_tenant_archived_unknown() -> None:
    admin = _admin()
    assert visible_to(
        Memory(scope="personal", owner_id="x", tenant_id="t2"), viewer=admin
    ) is False
    assert visible_to(
        Memory(scope="personal", owner_id="x", tenant_id=TENANT, archived=True),
        viewer=admin,
    ) is False
    assert visible_to({"scope": "org", "tenant_id": TENANT}, viewer=admin) is False


# --- promotion guard (G-1 / G-2) --------------------------------------------


def test_promotion_is_department_scoped_and_bounded() -> None:
    admin = _admin(department_ids={"d1"})
    memory = Memory(scope="personal", owner_id="u1", tenant_id=TENANT)
    with pytest.raises(MemoryAccessError):
        promote_to_department(memory, viewer=_viewer(), department_id="d1")
    with pytest.raises(MemoryAccessError):
        promote_to_department(memory, viewer=admin, department_id="d-outside")
    promoted = promote_to_department(memory, viewer=admin, department_id="d1")
    assert promoted.scope == MemoryScope.DEPARTMENT.value
    assert promoted.department_id == "d1"
    # A promoted department note is readable by a member of that department.
    assert visible_to(
        promoted, viewer=_viewer("u9", department_ids={"d1"})
    ) is True
