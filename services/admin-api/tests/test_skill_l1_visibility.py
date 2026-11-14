"""036 T018: FR-014 L1 owner-only visibility wired into the skill routes.

Covers both legs of the gap that ``ratings.list_ratings(visible_to=)`` alone did not
close: the catalogue/market listing must hide L1 skills from unrelated callers, and
the direct-read route must refuse them with the same 404 as "not found".
"""

from __future__ import annotations

from typing import Any

import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


from app.api.routes import skills as skills_module
from app.services.trust_rating import skill_visibility as visibility_module


def _now_text() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _skill(doc_id: str, name: str) -> dict[str, Any]:
    return {
        "_id": doc_id,
        "tenant_id": "t1",
        "name": name,
        "description": "d",
        "scenario": "s",
        "type": "ordinary",
        "config": {},
        "enabled": True,
        "created_at": _now_text(),
        "updated_at": _now_text(),
    }


def _rating(skill_key: str, *, level: str = "L1", owner: str = "u1") -> dict[str, Any]:
    return {
        "_id": f"r-{skill_key}",
        "tenant_id": "t1",
        "asset_type": "skill",
        "asset_key": skill_key,
        "level": level,
        "owner_id": owner,
        "created_by": owner,
        "updated_at": _now_text(),
    }


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._i = 0

    def sort(self, key: str, direction: int = -1) -> "_Cursor":
        self._rows = sorted(self._rows, key=lambda r: str(r.get(key) or ""), reverse=(direction < 0))
        return self

    def __aiter__(self) -> "_Cursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return list(self._rows[:length]) if length is not None else list(self._rows)


def _eq(row: dict[str, Any], flt: dict[str, Any]) -> bool:
    for key, value in flt.items():
        if row.get(key) != value:
            return False
    return True


class _Collection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find(self, flt: dict[str, Any], projection: dict[str, Any] | None = None) -> _Cursor:
        matched = [row for row in self.rows if _eq(row, flt)]
        if projection:
            matched = [
                {k: v for k, v in row.items() if k in projection or k == "_id"} for row in matched
            ]
        return _Cursor(matched)

    async def find_one(self, flt: dict[str, Any]) -> dict[str, Any] | None:
        for row in self.rows:
            if _eq(row, flt):
                return row
        return None


class _Db:
    def __init__(self) -> None:
        self.skills = _Collection([])
        self.trust_ratings = _Collection([])
        self.skill_adoption = _Collection([])

    def __getitem__(self, name: str) -> _Collection:
        if name == "skills":
            return self.skills
        if name == "trust_ratings":
            return self.trust_ratings
        if name == "skill_adoption":
            return self.skill_adoption
        raise KeyError(name)


@pytest.fixture
def db() -> _Db:
    return _Db()


@pytest.fixture
def viewer() -> dict[str, Any]:
    return {"_id": "u2", "tenant_id": "t1"}


@pytest.fixture
def owner() -> dict[str, Any]:
    return {"_id": "u1", "tenant_id": "t1"}


async def _no_marks(_db: _Db, *, tenant_id: str) -> set[str]:
    return set()


def _patch(monkeypatch: pytest.MonkeyPatch, db: _Db) -> None:
    monkeypatch.setattr(skills_module, "get_db", lambda: db)
    monkeypatch.setattr(skills_module, "fetch_marked_skill_keys", _no_marks)


def test_list_skills_hides_l1_from_other_viewer(
    monkeypatch: pytest.MonkeyPatch, db: _Db, viewer: dict[str, Any]
) -> None:
    db.skills.rows = [_skill("s1", "draft"), _skill("s2", "public")]
    db.trust_ratings.rows = [_rating("s1", owner="u1")]
    _patch(monkeypatch, db)
    rows = run(skills_module.list_skills(viewer))
    ids = {row["id"] for row in rows}
    assert "s1" not in ids
    assert "s2" in ids


def test_list_skills_shows_own_l1(
    monkeypatch: pytest.MonkeyPatch, db: _Db, owner: dict[str, Any]
) -> None:
    db.skills.rows = [_skill("s1", "mine")]
    db.trust_ratings.rows = [_rating("s1", owner="u1")]
    _patch(monkeypatch, db)
    rows = run(skills_module.list_skills(owner))
    assert {row["id"] for row in rows} == {"s1"}


def test_list_skills_hides_l2_from_no_one(
    monkeypatch: pytest.MonkeyPatch, db: _Db, viewer: dict[str, Any]
) -> None:
    db.skills.rows = [_skill("s1", "vetted")]
    db.trust_ratings.rows = [_rating("s1", level="L3", owner="u1")]
    _patch(monkeypatch, db)
    rows = run(skills_module.list_skills(viewer))
    assert {row["id"] for row in rows} == {"s1"}


def test_get_skill_rejects_foreign_l1(
    monkeypatch: pytest.MonkeyPatch, db: _Db, viewer: dict[str, Any]
) -> None:
    from fastapi import HTTPException

    db.skills.rows = [_skill("s1", "draft")]
    db.trust_ratings.rows = [_rating("s1", owner="u1")]
    _patch(monkeypatch, db)
    with pytest.raises(HTTPException) as exc_info:
        run(skills_module.get_skill("s1", viewer))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "技能不存在"


def test_get_skill_allows_owner_l1(
    monkeypatch: pytest.MonkeyPatch, db: _Db, owner: dict[str, Any]
) -> None:
    db.skills.rows = [_skill("s1", "mine")]
    db.trust_ratings.rows = [_rating("s1", owner="u1")]
    _patch(monkeypatch, db)
    row = run(skills_module.get_skill("s1", owner))
    assert row["id"] == "s1"


def test_assert_skill_visible_skips_when_no_viewer(db: _Db) -> None:
    run(visibility_module.assert_skill_visible(db, tenant_id="t1", viewer_id="", skill_key="s1"))


def test_assert_skill_visible_ok_when_unrated(db: _Db) -> None:
    run(visibility_module.assert_skill_visible(db, tenant_id="t1", viewer_id="u2", skill_key="s9"))


def test_hidden_l1_skill_ids_internal_view_empty(db: _Db) -> None:
    db.trust_ratings.rows = [_rating("s1", owner="u1")]
    hidden = run(visibility_module.hidden_l1_skill_ids(db, tenant_id="t1", viewer_id=""))
    assert hidden == set()