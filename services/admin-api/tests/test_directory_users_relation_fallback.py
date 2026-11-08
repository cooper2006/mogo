"""Regression: users must not silently disappear when org relations are missing.

The user-management page always sends ``departmentId`` (the tree auto-selects
its first node). ``list_users`` used to translate "no matching
``end_user_org_relations`` row" into ``_id: {$in: []}``, which hid every user
of a tenant whose data was imported without the relation table (e.g. only
``end_users`` was written).

The fallback must be narrow: it applies **only** when the tenant has no org
relations at all. A genuinely empty department in a tenant that does have
relations must stay empty, otherwise selecting an empty department would
wrongly list users from other departments.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.api.routes import directory

TENANT = "tenant-relation-fallback"
ROOT = "root-dept"
CHILD = "child-dept"
OTHER = "other-dept"

U1 = "a" * 24
U2 = "b" * 24
U3 = "c" * 24


def _match(doc: dict, flt: dict) -> bool:
    for key, cond in (flt or {}).items():
        value = doc.get(key)
        if isinstance(cond, dict) and "$in" in cond:
            allowed = {str(item) for item in cond["$in"]}
            if str(value) not in allowed:
                return False
        elif isinstance(cond, dict):
            # The tests only need equality and $in; any other operator means
            # "not matched" for this in-memory fixture.
            return False
        elif isinstance(value, (list, tuple)):
            # Mongo matches a scalar against any element of an array field,
            # e.g. {"path_ids": ROOT} hits a doc with path_ids: [ROOT].
            if not any(item == cond or str(item) == str(cond) for item in value):
                return False
        elif value != cond and str(value) != str(cond):
            return False
    return True


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def sort(self, *args: Any, **kwargs: Any) -> "_Cursor":
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self.rows[:length] if length else list(self.rows)


class _Col:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = list(docs or [])

    def find(self, flt: dict | None = None, projection: dict | None = None) -> _Cursor:
        return _Cursor([dict(doc) for doc in self.docs if _match(doc, flt or {})])


class _Mem:
    def __init__(self, **collections: list[dict]) -> None:
        self.cols: dict[str, _Col] = {name: _Col(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> _Col:
        return self.cols.setdefault(name, _Col())


def _departments() -> list[dict]:
    return [
        {"_id": ROOT, "tenant_id": TENANT, "name": "总部", "path_ids": [], "status": "active"},
        {"_id": CHILD, "tenant_id": TENANT, "name": "子部门", "path_ids": [ROOT], "status": "active"},
    ]


def _users() -> list[dict]:
    return [
        {"_id": U1, "tenant_id": TENANT, "name": "甲", "login_name": "u1", "primary_org_id": CHILD, "status": "active"},
        {"_id": U2, "tenant_id": TENANT, "name": "乙", "login_name": "u2", "primary_org_id": ROOT, "status": "active"},
        {"_id": U3, "tenant_id": TENANT, "name": "丙", "login_name": "u3", "primary_org_id": OTHER, "status": "active"},
        # Cross-tenant row must never leak through the fallback.
        {"_id": U3, "tenant_id": "some-other-tenant", "name": "外人", "login_name": "x", "status": "active"},
    ]


def _wire(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(directory, "get_db", lambda: mem)


async def _list(mem: _Mem, department_id: str | None = ROOT) -> list[dict]:
    return await directory.list_users(
        current_user={"tenant_id": TENANT, "username": "admin"},
        departmentId=department_id,
        # FastAPI injects these at request time; direct calls must pass None
        # explicitly, otherwise the Query descriptor objects are truthy.
        keyword=None,
        statusFilter=None,
        sourceFilter=None,
    )


@pytest.mark.asyncio
async def test_no_relations_falls_back_to_all_tenant_users(monkeypatch) -> None:
    """Imported tenant with an empty relation table still lists its users."""
    mem = _Mem(
        **{
            directory.USER_COLLECTION: _users(),
            directory.DEPARTMENT_COLLECTION: _departments(),
            directory.USER_ORG_REL_COLLECTION: [],
        }
    )
    _wire(monkeypatch, mem)

    rows = await _list(mem)

    assert {row["id"] for row in rows} == {U1, U2, U3}
    # primaryDepartmentId falls back to end_users.primary_org_id when no
    # relation row exists (existing behaviour in the projection).
    assert {row["primaryDepartmentId"] for row in rows} == {CHILD, ROOT, OTHER}


@pytest.mark.asyncio
async def test_empty_department_stays_empty_when_relations_exist(monkeypatch) -> None:
    """A department with no members must not show users from other departments."""
    mem = _Mem(
        **{
            directory.USER_COLLECTION: _users(),
            directory.DEPARTMENT_COLLECTION: _departments(),
            directory.USER_ORG_REL_COLLECTION: [
                {"tenant_id": TENANT, "user_id": U1, "org_id": "unrelated-dept", "is_primary": True},
            ],
        }
    )
    _wire(monkeypatch, mem)

    assert await _list(mem) == []


@pytest.mark.asyncio
async def test_department_filter_unchanged_when_relations_exist(monkeypatch) -> None:
    """Normal path still restricts the list to the selected department subtree."""
    mem = _Mem(
        **{
            directory.USER_COLLECTION: _users(),
            directory.DEPARTMENT_COLLECTION: _departments(),
            directory.USER_ORG_REL_COLLECTION: [
                {"tenant_id": TENANT, "user_id": U1, "org_id": CHILD, "is_primary": True},
            ],
        }
    )
    _wire(monkeypatch, mem)

    rows = await _list(mem)

    assert [row["id"] for row in rows] == [U1]
    assert rows[0]["primaryDepartmentId"] == CHILD


@pytest.mark.asyncio
async def test_without_department_id_lists_all_tenant_users(monkeypatch) -> None:
    """No departmentId keeps the original, unfiltered tenant scope."""
    mem = _Mem(
        **{
            directory.USER_COLLECTION: _users(),
            directory.DEPARTMENT_COLLECTION: _departments(),
            directory.USER_ORG_REL_COLLECTION: [],
        }
    )
    _wire(monkeypatch, mem)

    rows = await _list(mem, department_id=None)

    assert {row["id"] for row in rows} == {U1, U2, U3}
