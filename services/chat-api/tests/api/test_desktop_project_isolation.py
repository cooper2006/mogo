from __future__ import annotations

import asyncio

from app.api.endpoints import projects


def _match(document: dict, scope: dict) -> bool:
    """049：fake 集合的最小过滤语义（等值 / 数组包含 / $or）。"""
    for key, value in scope.items():
        if key == "$or":
            if not any(_match(document, branch) for branch in value):
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

    async def update_one(self, scope: dict, update: dict, upsert: bool = False) -> None:
        document = next((item for item in self.documents if _match(item, scope)), None)
        if document is None:
            assert upsert
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            # pg_compat 的 INSERT ... ON CONFLICT (id) DO NOTHING：id 全局唯一。
            if any(item.get("_id") == document.get("_id") for item in self.documents):
                return None
            self.documents.append(document)
        document.update(update.get("$set", {}))

    async def find_one(self, scope: dict):
        return next((item for item in self.documents if _match(item, scope)), None)

    def find(self, scope: dict) -> _Cursor:
        return _Cursor([item for item in self.documents if _match(item, scope)])


class _Database:
    def __init__(self) -> None:
        self.projects = _ProjectCollection()



def test_projects_are_bound_to_authenticated_employee(monkeypatch) -> None:
    database = _Database()

    async def identity(authorization: str | None):
        assert authorization
        tenant_id, user_id = authorization.split(":", 1)
        return tenant_id, user_id

    monkeypatch.setattr(projects, "get_db", lambda: database)
    monkeypatch.setattr(projects, "_identity", identity)

    async def scenario() -> None:
        await projects.create_desktop_project(
            projects.DesktopProjectCreate(workspace_id="alice-workspace", title="Alice", worktree=False),
            authorization="tenant:alice",
        )
        await projects.create_desktop_project(
            projects.DesktopProjectCreate(workspace_id="bob-workspace", title="Bob", worktree=False),
            authorization="tenant:bob",
        )

        alice = await projects.list_desktop_projects(authorization="tenant:alice")
        bob = await projects.list_desktop_projects(authorization="tenant:bob")
        # 046 FR-003: 首次 list 会幂等生成 `_id = "default"` 的默认项目。
        assert sorted(item["workspace_id"] for item in alice.data) == ["", "alice-workspace"]
        assert sorted(item["workspace_id"] for item in bob.data) == ["", "bob-workspace"]
        # 049：默认项目 `_id = "default"` 在存储层全局唯一，是租户共享兜底项；
        # 真实项目仍按 user_id 隔离。
        assert {item["_id"] for item in alice.data} == {"default", "alice-workspace"}
        assert {item["_id"] for item in bob.data} == {"default", "bob-workspace"}
        assert [item["status"] for item in alice.data] == ["active", "active"]

    asyncio.run(scenario())
