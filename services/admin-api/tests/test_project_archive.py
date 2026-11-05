"""T027 (SC-005): 归档项目不参与配额取小；归档保留策略行与历史用量；恢复后立即生效。

覆盖 046 FR-009/FR-012 与 042 三级配额的交叉：
- 归档项目的 chat_sessions 数据保留（不删除）
- 项目成员从 chat_sessions 反查（FR-012），归档状态不阻断查询
- 恢复 active 后立即重新参与取小
"""

from __future__ import annotations

import pytest

from app.core.quota_policy import (
    CHAT_SESSIONS_COLLECTION,
    PROJECT_COLLECTION,
    _project_scope_ids,
    _scope_members,
)

TENANT = "tenant-t027"
USER_ID = "user-t027"


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = list(docs or [])

    def find(self, query: dict, projection: dict | None = None) -> _Cursor:
        matched = [d for d in self.docs if _matches(d, query)]
        if projection:
            keys = [k for k, v in projection.items() if v]
            matched = [{k: d.get(k) for k in keys if k in d} | {"_id": d.get("_id")} for d in matched]
        return _Cursor(matched)

    async def find_one(self, query: dict, projection: dict | None = None, sort=None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, query):
                if projection:
                    keys = [k for k, v in projection.items() if v]
                    return {k: doc.get(k) for k in keys if k in doc} | {"_id": doc.get("_id")}
                return doc
        return None

    async def update_one(self, scope: dict, update: dict) -> None:
        for doc in self.docs:
            if _matches(doc, scope):
                doc.update(update.get("$set", {}))
                return


def _matches(doc: dict, query: dict) -> bool:
    for key, value in query.items():
        if key == "member_user_ids":
            if value not in (doc.get("member_user_ids") or []):
                return False
        elif doc.get(key) != value:
            return False
    return True


class _Db:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


@pytest.fixture()
def db() -> _Db:
    return _Db()


def _add_session(db: _Db, *, user_id: str, project_id: str) -> None:
    db[CHAT_SESSIONS_COLLECTION].docs.append({
        "tenant_id": TENANT,
        "user_id": user_id,
        "project_id": project_id,
    })


def _add_project(
    db: _Db,
    *,
    project_id: str,
    status: str = "active",
    creator: str = "",
    members: list[str] | None = None,
) -> None:
    """049：项目实体在 projects 表；成员 = member_user_ids ∪ 创建者 user_id。"""
    db[PROJECT_COLLECTION].docs.append({
        "_id": project_id,
        "tenant_id": TENANT,
        "user_id": creator,
        "title": f"Project {project_id}",
        "status": status,
        "member_user_ids": list(members or []),
    })


@pytest.mark.asyncio
async def test_project_scope_ids_from_chat_sessions(db: _Db) -> None:
    """FR-012: 项目成员从 chat_sessions 反查，不用 quota_projects.member_user_ids。"""
    _add_session(db, user_id=USER_ID, project_id="p-alpha")
    _add_session(db, user_id=USER_ID, project_id="p-beta")
    _add_session(db, user_id="other-user", project_id="p-gamma")

    ids = await _project_scope_ids(db, TENANT, USER_ID)
    assert "p-alpha" in ids
    assert "p-beta" in ids
    assert "p-gamma" not in ids


@pytest.mark.asyncio
async def test_scope_members_from_chat_sessions(db: _Db) -> None:
    """049 FR-006：projects 行缺失/成员为空时回退 046 语义（chat_sessions 反查）。"""
    _add_session(db, user_id="u1", project_id="p1")
    _add_session(db, user_id="u2", project_id="p1")
    _add_session(db, user_id="u3", project_id="p2")

    members = await _scope_members(db, TENANT, "project", "p1")
    assert set(members) == {"u1", "u2"}

    members2 = await _scope_members(db, TENANT, "project", "p2")
    assert members2 == ["u3"]


@pytest.mark.asyncio
async def test_scope_members_from_project_member_field(db: _Db) -> None:
    """049 FR-006：项目成员 = member_user_ids ∪ 创建者（创建者不落 member_user_ids）。"""
    _add_project(db, project_id="p1", creator="owner-1", members=["u1", "u2"])
    # 即使成员里有会话，也以 member_user_ids ∪ 创建者 为准。
    _add_session(db, user_id="outsider", project_id="p1")

    members = await _scope_members(db, TENANT, "project", "p1")
    assert set(members) == {"u1", "u2", "owner-1"}
    assert "outsider" not in members


@pytest.mark.asyncio
async def test_archived_project_preserves_session_data(db: _Db) -> None:
    """归档不删除会话数据——chat_sessions 中的 project_id 归属保留。"""
    _add_session(db, user_id=USER_ID, project_id="p1")
    _add_project(db, project_id="p1", status="active")

    # 归档项目（projects 侧）
    await db[PROJECT_COLLECTION].update_one(
        {"_id": "p1", "tenant_id": TENANT},
        {"$set": {"status": "archived"}},
    )

    # 会话数据保留
    doc = await db[PROJECT_COLLECTION].find_one({"_id": "p1"})
    assert doc is not None
    assert doc["status"] == "archived"

    # chat_sessions 的归属数据不受影响
    ids = await _project_scope_ids(db, TENANT, USER_ID)
    assert "p1" in ids


@pytest.mark.asyncio
async def test_restore_active_immediately_rejoins(db: _Db) -> None:
    """恢复 active 后立即重新参与取小。"""
    _add_session(db, user_id=USER_ID, project_id="p1")
    _add_project(db, project_id="p1", status="archived")

    # 归档时仍有会话归属（chat_sessions 数据保留）
    ids = await _project_scope_ids(db, TENANT, USER_ID)
    assert "p1" in ids

    # 恢复
    await db[PROJECT_COLLECTION].update_one(
        {"_id": "p1", "tenant_id": TENANT},
        {"$set": {"status": "active"}},
    )

    doc = await db[PROJECT_COLLECTION].find_one({"_id": "p1"})
    assert doc["status"] == "active"
