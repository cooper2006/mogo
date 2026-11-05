"""049-project-members：项目成员可见性、成员管理与候选端点。

与 ``test_projects_rename.py`` 同款 fake 集合（无 Mongo 时 motor 由 conftest 桩
替代），只 monkeypatch ``get_db`` 与 ``_identity``，直接调用端点函数。

覆盖：
- FR-002 可见性：我的 ∪ 我作为成员的 ∪ 本租户默认项目。
- FR-003 成员管理权归创建者（非创建者 403、默认项目 400）。
- FR-001 成员字段归一化（去空、去重、创建者不落库）。
- FR-004 候选端点：部门子树过滤 + 仅 active 用户。
"""

from __future__ import annotations

import pytest

from app.api.endpoints import projects


def _match(document: dict, scope: dict) -> bool:
    for key, value in scope.items():
        if key == "$or":
            if not any(_match(document, branch) for branch in value):
                return False
            continue
        if isinstance(value, dict) and "$regex" in value:
            import re
            actual = document.get(key)
            flags = re.IGNORECASE if value.get("$options") == "i" else 0
            if actual is None or not re.search(str(value["$regex"]), str(actual), flags):
                return False
            continue
        if isinstance(value, dict) and "$in" in value:
            if document.get(key) not in value["$in"]:
                return False
            continue
        actual = document.get(key)
        if isinstance(actual, list) and not isinstance(value, list):
            if value not in actual:
                return False
            continue
        if actual != value:
            return False
    return True


class _Cursor:
    def __init__(self, documents: list[dict]) -> None:
        self._documents = documents

    def sort(self, _field: str, _direction: int):
        return self

    def __aiter__(self):
        self._iterator = iter(self._documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def to_list(self, length: int | None = None):
        return list(self._documents if length is None else self._documents[:length])


class _UpdateResult:
    def __init__(self, document: dict | None) -> None:
        self.upserted_id = document.get("_id") if document else None
        self.matched_count = 1 if document else 0
        self.modified_count = 1 if document else 0


class _Collection:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        document = next((item for item in self.documents if _match(item, scope)), None)
        if document is None:
            if not upsert:
                return _UpdateResult(None)
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            if any(item.get("_id") == document.get("_id") for item in self.documents):
                return _UpdateResult(None)  # ON CONFLICT (id) DO NOTHING
            self.documents.append(document)
        document.update(update.get("$set", {}))
        return _UpdateResult(document)

    async def find_one(self, scope: dict, projection: dict | None = None):
        return next((item for item in self.documents if _match(item, scope)), None)

    def find(self, scope: dict, projection: dict | None = None) -> _Cursor:
        return _Cursor([item for item in self.documents if _match(item, scope)])


class _Database:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def __getattr__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())

    def __getitem__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


async def _identity(authorization: str | None) -> tuple[str, str]:
    assert authorization
    tenant_id, user_id = authorization.split(":", 1)
    return tenant_id, user_id


@pytest.fixture
def db(monkeypatch):
    database = _Database()
    monkeypatch.setattr(projects, "get_db", lambda: database)
    monkeypatch.setattr(projects, "_identity", _identity)
    yield database
    for collection in database._collections.values():
        collection.documents.clear()


def _seed_project(db, project_id: str, user_id: str, *, title: str = "", members=None, status: str = "active") -> None:
    db.projects.documents.append({
        "_id": project_id,
        "tenant_id": "tenant",
        "user_id": user_id,
        "workspace_id": project_id,
        "title": title or project_id,
        "status": status,
        "member_user_ids": list(members or []),
    })


def _seed_user(db, user_id: str, name: str, *, status: str = "active") -> None:
    db["end_users"].documents.append({
        "_id": user_id, "tenant_id": "tenant", "name": name,
        "login_name": user_id, "status": status,
    })


@pytest.mark.asyncio
async def test_member_sees_creator_project(db):
    """049 FR-002：成员能看到自己参与的项目；非成员看不到。"""
    _seed_project(db, "p-alice", "alice", title="Alice 项目", members=["bob"])
    _seed_project(db, "p-carol", "carol", title="Carol 项目")

    bob = await projects.list_desktop_projects(authorization="tenant:bob")
    bob_ids = {item["_id"] for item in bob.data}
    assert "p-alice" in bob_ids          # 我作为成员的
    assert "p-carol" not in bob_ids      # 与我无关的
    assert "default" in bob_ids          # 本租户默认项目

    dave = await projects.list_desktop_projects(authorization="tenant:dave")
    assert {item["_id"] for item in dave.data} == {"default"}


@pytest.mark.asyncio
async def test_creator_can_manage_members(db):
    """049 FR-001/FR-003：仅创建者可改成员；创建者自身不落 member_user_ids。"""
    _seed_project(db, "p-alice", "alice", title="Alice 项目")
    response = await projects.patch_project(
        "p-alice",
        projects.ProjectPatch(member_user_ids=["bob", "carol", "", "bob", "alice"]),
        authorization="tenant:alice",
    )
    assert response.code == 0
    assert response.data["member_user_ids"] == ["bob", "carol"]

    stored = await db.projects.find_one({"tenant_id": "tenant", "_id": "p-alice"})
    assert stored["member_user_ids"] == ["bob", "carol"]


@pytest.mark.asyncio
async def test_member_cannot_manage_members(db):
    """049 US1 场景 4：非创建者 PATCH 成员 → 403，数据不被改写。"""
    _seed_project(db, "p-alice", "alice", members=["bob"])
    response = await projects.patch_project(
        "p-alice",
        projects.ProjectPatch(member_user_ids=["bob", "carol"]),
        authorization="tenant:bob",
    )
    assert response.code == 403
    stored = await db.projects.find_one({"tenant_id": "tenant", "_id": "p-alice"})
    assert stored["member_user_ids"] == ["bob"]


@pytest.mark.asyncio
async def test_default_project_members_rejected(db):
    """049 Edge：默认项目拒绝成员变更（400）。"""
    _seed_project(db, projects.DEFAULT_PROJECT_ID, "alice", title="默认项目")
    response = await projects.patch_project(
        projects.DEFAULT_PROJECT_ID,
        projects.ProjectPatch(member_user_ids=["bob"]),
        authorization="tenant:alice",
    )
    assert response.code == 400


@pytest.mark.asyncio
async def test_member_candidates_filtered_by_department_subtree(db):
    """049 FR-004：候选按部门及下级子树过滤，且只返回 active 用户。"""
    db["org_units"].documents.extend([
        {"_id": "dept-root", "tenant_id": "tenant", "name": "总部", "status": "active", "path_ids": []},
        {"_id": "dept-dev", "tenant_id": "tenant", "name": "研发", "status": "active", "path_ids": ["dept-root"]},
        {"_id": "dept-other", "tenant_id": "tenant", "name": "市场", "status": "active", "path_ids": []},
        {"_id": "dept-old", "tenant_id": "tenant", "name": "旧部门", "status": "archived", "path_ids": []},
    ])
    _seed_user(db, "alice", "Alice")
    _seed_user(db, "bob", "Bob")
    _seed_user(db, "carol", "Carol")
    _seed_user(db, "gone", "Gone", status="disabled")
    db["end_user_org_relations"].documents.extend([
        {"tenant_id": "tenant", "user_id": "alice", "org_id": "dept-dev", "is_primary": True},
        {"tenant_id": "tenant", "user_id": "bob", "org_id": "dept-dev", "is_primary": True},
        {"tenant_id": "tenant", "user_id": "carol", "org_id": "dept-other", "is_primary": True},
        {"tenant_id": "tenant", "user_id": "gone", "org_id": "dept-dev", "is_primary": True},
    ])

    subtree = await projects.list_project_member_candidates(
        department_id="dept-root", keyword="", authorization="tenant:alice",
    )
    assert {item["id"] for item in subtree.data["items"]} == {"alice", "bob"}
    assert all(item["departmentName"] == "研发" for item in subtree.data["items"])

    all_active = await projects.list_project_member_candidates(
        department_id="", keyword="", authorization="tenant:alice",
    )
    assert {item["id"] for item in all_active.data["items"]} == {"alice", "bob", "carol"}

    searched = await projects.list_project_member_candidates(
        department_id="", keyword="car", authorization="tenant:alice",
    )
    assert {item["id"] for item in searched.data["items"]} == {"carol"}


@pytest.mark.asyncio
async def test_departments_endpoint_returns_active_only(db):
    """049 FR-004：弹窗部门树只含 active 部门。"""
    db["org_units"].documents.extend([
        {"_id": "root", "tenant_id": "tenant", "name": "总部", "status": "active", "path_ids": []},
        {"_id": "dev", "tenant_id": "tenant", "name": "研发", "status": "active", "path_ids": ["root"]},
        {"_id": "old", "tenant_id": "tenant", "name": "旧部门", "status": "archived", "path_ids": []},
    ])
    response = await projects.list_project_departments(authorization="tenant:alice")
    departments = response.data["departments"]
    assert {item["id"] for item in departments} == {"root", "dev"}
    assert departments[0]["id"] == "root"  # depth 0 在前
    assert departments[1]["depth"] == 1
