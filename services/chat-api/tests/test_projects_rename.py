"""046 P0 项目实体：集合改名后 CRUD 全通 + 默认项目幂等 + 默认项目不可归档 (T007)。

本地无 MongoDB 时 motor 由 conftest 桩替代；所有断言只依赖模块内的
`_ensure_default_project` / `_serialize_project` / `get_db` monkeypatch。
"""

from __future__ import annotations

import pytest

from app.api.endpoints import projects


def _match(document: dict, scope: dict) -> bool:
    """049：fake 集合的最小过滤语义（等值 / $in / 数组包含 / $or）。"""
    for key, value in scope.items():
        if key == "$or":
            if not any(_match(document, branch) for branch in value):
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


class _ProjectCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.last_update_one_scope: dict | None = None
        self.last_update_one_update: dict | None = None

    async def update_one(self, scope: dict, update: dict, upsert: bool = False):
        self.last_update_one_scope = scope
        self.last_update_one_update = update
        document = next((item for item in self.documents if _match(item, scope)), None)
        if document is None:
            if not upsert:
                return _UpdateResult(None)
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            # pg_compat 的 INSERT ... ON CONFLICT (id) DO NOTHING：id 全局唯一。
            if any(item.get("_id") == document.get("_id") for item in self.documents):
                return _UpdateResult(None)
            self.documents.append(document)
        document.update(update.get("$set", {}))
        return _UpdateResult(document)

    async def update_many(self, scope, update):
        return _UpdateResult(None)

    async def find_one(self, scope: dict):
        return next((item for item in self.documents if _match(item, scope)), None)

    def find(self, scope: dict) -> _Cursor:
        return _Cursor([item for item in self.documents if _match(item, scope)])


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
    """046 FR-003/D2 + 多租户：每个租户各有一份默认项目，对外都是 ``"default"``。

    Mongo ``_id`` 是集合级全局唯一，所以物理主键按租户分片为
    ``default:<tenant_id>``；早期用裸 ``"default"`` 当物理主键会让第二个租户
    upsert 撞 E11000。同租户第二个用户复用同一份，不新建第二行。
    """
    await _create("Alice", "alice-workspace")
    doc_id = projects._default_project_doc_id("tenant")
    for _ in range(3):
        await projects.list_desktop_projects(authorization="tenant:alice")

    defaults = [d for d in db.projects.documents if d.get("is_default")]
    assert len(defaults) == 1
    assert defaults[0]["_id"] == doc_id
    assert defaults[0]["title"] == "默认项目"
    assert defaults[0]["status"] == "active"
    assert defaults[0]["tenant_id"] == "tenant"
    assert defaults[0]["user_id"] == "alice"

    # 同租户第二个用户复用同一份默认项目，且看不到 alice 的真实项目。
    await projects.list_desktop_projects(authorization="tenant:bob")
    defaults = [d for d in db.projects.documents if d.get("is_default")]
    assert len(defaults) == 1
    alice_docs = {d["_id"] for d in db.projects.documents if d["user_id"] == "alice"}
    bob_docs = {d["_id"] for d in db.projects.documents if d["user_id"] == "bob"}
    assert alice_docs == {doc_id, "alice-workspace"}
    assert bob_docs == set()
    bob_visible = await projects.list_desktop_projects(authorization="tenant:bob")
    assert {item["_id"] for item in bob_visible.data} == {"default"}

    # 跨租户：另一个租户生成自己的一份，物理主键不冲突、数据不串。
    await projects.list_desktop_projects(authorization="other-tenant:carol")
    defaults = [d for d in db.projects.documents if d.get("is_default")]
    assert len(defaults) == 2
    assert {d["_id"] for d in defaults} == {
        doc_id,
        projects._default_project_doc_id("other-tenant"),
    }
    carol_visible = await projects.list_desktop_projects(authorization="other-tenant:carol")
    assert {item["_id"] for item in carol_visible.data} == {"default"}
    assert all(item["tenant_id"] == "other-tenant" for item in carol_visible.data)


@pytest.mark.asyncio
async def test_default_project_cannot_be_archived(db):
    """046 Edge Case 3：默认项目不可归档，返回明确错误。"""
    await projects.list_desktop_projects(authorization="tenant:alice")
    response = await _patch(projects.DEFAULT_PROJECT_ID, "archived")
    assert response.code == 400
    assert response.message == "默认项目不可归档或删除"
    # 物理分片 id 也不能绕过 046 Edge Case 3。
    physical = await _patch(projects._default_project_doc_id("tenant"), "archived")
    assert physical.code == 400
    # 状态未被篡改（按物理主键查询）。
    item = await projects.get_db().projects.find_one(
        {"tenant_id": "tenant", "user_id": "alice", "_id": projects._default_project_doc_id("tenant")}
    )
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
        "status", "member_user_ids", "created_at", "updated_at",
    }
    assert serialized["member_user_ids"] == []
