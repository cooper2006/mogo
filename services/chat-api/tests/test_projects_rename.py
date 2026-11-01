"""046 P0 项目实体：集合改名后 CRUD 全通 + 默认项目幂等 + 默认项目不可归档 (T007)。

本地无 MongoDB 时 motor 由 conftest 桩替代；所有断言只依赖模块内的
`_ensure_default_project` / `_serialize_project` / `get_db` monkeypatch。
"""

from __future__ import annotations

import pytest

from app.api.endpoints import projects


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


class _ProjectCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.last_update_one_scope: dict | None = None
        self.last_update_one_update: dict | None = None

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        self.last_update_one_scope = scope
        self.last_update_one_update = update
        document = next((item for item in self.documents if all(item.get(key) == value for key, value in scope.items())), None)
        if document is None:
            if not upsert:
                return _UpdateResult(None)
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            self.documents.append(document)
        document.update(update.get("$set", {}))
        return _UpdateResult(document)

    async def update_many(self, scope, update):
        return _UpdateResult(None)

    async def find_one(self, scope: dict):
        return next((item for item in self.documents if all(item.get(key) == value for key, value in scope.items())), None)

    def find(self, scope: dict) -> _Cursor:
        return _Cursor([
            item for item in self.documents
            if all(item.get(key) == value for key, value in scope.items())
        ])


class _UpdateResult:
    def __init__(self, document: dict | None) -> None:
        self.upserted_id = document.get("_id") if document else None
        self.modified_count = 1 if document else 0
        self.matched_count = 1 if document else 0


class _Database:
    def __init__(self) -> None:
        self.projects = _ProjectCollection()


async def _identity(authorization: str | None) -> tuple[str, str]:
    """与 `projects._identity` 一致：`resolve_tenant_id` 对 ``tenant:alice`` 是恒等映射。"""
    assert authorization
    tenant_id, user_id = authorization.split(":", 1)
    return tenant_id, user_id


@pytest.fixture
def db(monkeypatch):
    """每个测试拿到一份干净的数据库，并切掉异步测试的 loop 缓存副作用。"""
    database = _Database()
    monkeypatch.setattr(projects, "get_db", lambda: database)
    monkeypatch.setattr(projects, "_identity", _identity)
    yield database
    database.projects.documents.clear()


async def _create(title: str, workspace: str, authorization: str = "tenant:alice"):
    """`authorization` 决定归属；默认 alice 用于隔离性断言。"""
    await projects.create_desktop_project(
        projects.DesktopProjectCreate(workspace_id=workspace, title=title, worktree=False),
        authorization=authorization,
    )


async def _patch(project_id: str, status: str, authorization: str = "tenant:alice"):
    return await projects.patch_project(
        project_id,
        projects.ProjectPatch(status=status),
        authorization=authorization,
    )


@pytest.mark.asyncio
async def test_crud_survives_collection_rename(db):
    """046 FR-001/FR-013：改名后 CRUD 全通，HTTP 契约不变。"""
    await _create("Alice", "alice-workspace")
    await _create("Bob", "bob-workspace", authorization="tenant:bob")

    alice = await projects.list_desktop_projects(authorization="tenant:alice")
    ids = {item["_id"] for item in alice.data}
    assert ids == {"alice-workspace", "default"}

    item = await projects.get_db().projects.find_one({"tenant_id": "tenant", "user_id": "alice", "_id": "alice-workspace"})
    assert item["title"] == "Alice"
    assert item["status"] == "active"
    assert item["workspace_id"] == "alice-workspace"


@pytest.mark.asyncio
async def test_default_project_is_idempotent(db):
    """046 FR-003/D2：重复 list 只产生一条 `_id = "default"` 的默认项目。"""
    await _create("Alice", "alice-workspace")
    for _ in range(3):
        await projects.list_desktop_projects(authorization="tenant:alice")

    defaults = [d for d in db.projects.documents if d["_id"] == projects.DEFAULT_PROJECT_ID]
    assert len(defaults) == 1
    assert defaults[0]["title"] == "默认项目"
    assert defaults[0]["status"] == "active"
    assert defaults[0]["tenant_id"] == "tenant"
    assert defaults[0]["user_id"] == "alice"

    # 另一个租户拿到自己的默认项目，互不可见（046 US1 场景 4）。
    await projects.list_desktop_projects(authorization="tenant:bob")
    alice_docs = {d["_id"] for d in db.projects.documents if d["user_id"] == "alice"}
    bob_docs = {d["_id"] for d in db.projects.documents if d["user_id"] == "bob"}
    assert alice_docs == {"default", "alice-workspace"}
    assert bob_docs == {"default"}


@pytest.mark.asyncio
async def test_default_project_cannot_be_archived(db):
    """046 Edge Case 3：默认项目不可归档，返回明确错误。"""
    await projects.list_desktop_projects(authorization="tenant:alice")
    response = await _patch(projects.DEFAULT_PROJECT_ID, "archived")
    assert response.code == 400
    assert response.message == "默认项目不可归档或删除"
    # 状态未被篡改。
    item = await projects.get_db().projects.find_one({"tenant_id": "tenant", "user_id": "alice", "_id": projects.DEFAULT_PROJECT_ID})
    assert item["status"] == "active"


@pytest.mark.asyncio
async def test_real_project_can_be_archived_and_restored(db):
    """046 FR-009/D7：真实项目两态切换。"""
    await _create("Alice", "alice-workspace")
    response = await _patch("alice-workspace", "archived")
    assert response.code == 0
    assert response.data["status"] == "archived"

    restored = await _patch("alice-workspace", "active")
    assert restored.code == 0
    assert restored.data["status"] == "active"


@pytest.mark.asyncio
async def test_patch_unknown_project_returns_404(db):
    await projects.list_desktop_projects(authorization="tenant:alice")
    response = await _patch("does-not-exist", "archived")
    assert response.code == 404


@pytest.mark.asyncio
async def test_patch_only_accepts_status(db):
    """046 T025：PATCH 只接受 status 字段变更。"""
    await _create("Alice", "alice-workspace")
    response = await _patch("alice-workspace", "active")
    assert response.code == 0
    assert response.data["title"] == "Alice"
    assert response.data["workspace_id"] == "alice-workspace"


@pytest.mark.asyncio
async def test_create_and_list_serialize_all_fields(db):
    """046 FR-002：projects 记录 tenant_id / user_id / status / 时间戳。"""
    await _create("Alice", "alice-workspace")
    item = await projects.get_db().projects.find_one({"tenant_id": "tenant", "user_id": "alice", "_id": "alice-workspace"})
    assert item["tenant_id"] == "tenant"
    assert item["user_id"] == "alice"
    assert item["status"] == "active"
    assert item["created_at"] is not None
    assert item["updated_at"] is not None

    serialized = projects._serialize_project(item)
    assert set(serialized) == {
        "_id", "tenant_id", "user_id", "workspace_id", "title", "worktree",
        "status", "created_at", "updated_at",
    }
