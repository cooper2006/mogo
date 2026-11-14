"""T037 H-6: archiving a 049 project must explicitly invalidate its memories.

The canonical 049 archive path is ``PATCH /projects/{id}`` with ``status=archived``
in ``app.api.endpoints.projects.patch_project``. Per H-6, that path must call
``invalidate_project_memories`` so the project's memories exit RAG default
retrieval (scope.visible_to is fail-closed on ``invalidated``).

Mirrors ``test_desktop_project_isolation`` fixtures but extends the fake DB with a
``memories`` collection, so the offboarding call runs without a live Mongo.
"""
from __future__ import annotations

import asyncio
from typing import Any

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


class _MemoriesCursor:
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


class _ProjectResult:
    def __init__(self, matched: int) -> None:
        self.matched_count = matched


class _ProjectCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def update_one(self, scope: dict, update: dict, upsert: bool = False) -> _ProjectResult:
        document = next((item for item in self.documents if _match(item, scope)), None)
        if document is None:
            assert upsert
            document = dict(scope)
            document.update(update.get("$setOnInsert", {}))
            if any(item.get("_id") == document.get("_id") for item in self.documents):
                return None  # mimic DuplicateKeyError on id collision
            self.documents.append(document)
            document.update(update.get("$set", {}))
            return _ProjectResult(1)
        document.update(update.get("$set", {}))
        return _ProjectResult(1)

    async def find_one(self, scope: dict):
        return next((item for item in self.documents if _match(item, scope)), None)

    def find(self, scope: dict) -> _MemoriesCursor:
        return _MemoriesCursor([item for item in self.documents if _match(item, scope)])


class _MemoryResult:
    def __init__(self, modified: int) -> None:
        self.modified_count = modified


class _MemoryCollection:
    """update_many supporting $ne / $or / $set (mirrors offboarding unit fake)."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    async def update_many(self, query: dict, update: dict) -> _MemoryResult:
        set_fields = update.get("$set", {})
        modified = 0
        for row in self.documents:
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
        return _MemoryResult(modified)


class _Database:
    def __init__(self) -> None:
        self.projects = _ProjectCollection()
        self.memories = _MemoryCollection()

    def __getitem__(self, name: str):
        # offboarding uses db[COLLECTION]; route to the memories collection.
        return getattr(self, name, None) or self.memories


def test_archiving_project_invalidates_its_memories(monkeypatch) -> None:
    database = _Database()
    tenant_id, owner_id = "tenant", "alice"

    async def identity(authorization: str | None):
        return tenant_id, owner_id

    monkeypatch.setattr(projects, "get_db", lambda: database)
    monkeypatch.setattr(projects, "_identity", identity)
    # offboarding resolves tenant_id; keep identity so seeded docs match the query.
    import app.memory.offboarding as offboarding_mod

    monkeypatch.setattr(offboarding_mod, "resolve_tenant_id", lambda t: t)
    # audit bridge may be unavailable in CI; make emit a no-op so it never errors.
    try:
        import app.services.feature_audit_bridge as bridge

        def _noop_emit(*_a, **_k):
            return None

        monkeypatch.setattr(bridge, "emit_feature_event", _noop_emit)
    except Exception:
        pass

    async def scenario() -> None:
        await projects.create_desktop_project(
            projects.DesktopProjectCreate(workspace_id="alice-ws", title="Alice", worktree=False),
            authorization="tenant:alice",
        )
        project = next(p for p in database.projects.documents if p.get("workspace_id") == "alice-ws")
        pid = project["_id"]
        # Two project memories sharing the project id: one owned by alice (should
        # be invalidated), one owned by bob (N1 disambiguator -> must survive).
        database.memories.documents = [
            {
                "tenant_id": tenant_id,
                "scope": "project",
                "project_id": pid,
                "project_owner_id": owner_id,
                "archived": False,
                "invalidated": False,
                "content": "owned",
            },
            {
                "tenant_id": tenant_id,
                "scope": "project",
                "project_id": pid,
                "project_owner_id": "bob",
                "archived": False,
                "invalidated": False,
                "content": "other-owner",
            },
        ]
        resp = await projects.patch_project(
            pid,
            projects.ProjectPatch(status="archived"),
            authorization="tenant:alice",
        )
        assert resp.code == 0
        assert resp.data["status"] == "archived"

        docs = {d["content"]: d for d in database.memories.documents}
        assert docs["owned"]["invalidated"] is True
        assert docs["owned"]["invalidated_reason"] == "project_archived"
        # 不同 owner 的同项目记忆按 N1 不被误伤。
        assert docs["other-owner"]["invalidated"] is False

    asyncio.run(scenario())


def test_archiving_project_invalidation_failure_does_not_block_patch(monkeypatch) -> None:
    """H-6 失败必须 fail-safe：失效调用抛错也不能阻断归档响应。"""
    database = _Database()
    tenant_id, owner_id = "tenant", "alice"

    async def identity(authorization: str | None):
        return tenant_id, owner_id

    class _BoomCollection:
        async def update_many(self, query: dict, update: dict):
            raise RuntimeError("mongo down")

    database.memories = _BoomCollection()  # type: ignore[assignment]

    monkeypatch.setattr(projects, "get_db", lambda: database)
    monkeypatch.setattr(projects, "_identity", identity)
    import app.memory.offboarding as offboarding_mod

    monkeypatch.setattr(offboarding_mod, "resolve_tenant_id", lambda t: t)

    async def scenario() -> None:
        await projects.create_desktop_project(
            projects.DesktopProjectCreate(workspace_id="alice-ws", title="Alice", worktree=False),
            authorization="tenant:alice",
        )
        project = next(p for p in database.projects.documents if p.get("workspace_id") == "alice-ws")
        resp = await projects.patch_project(
            project["_id"],
            projects.ProjectPatch(status="archived"),
            authorization="tenant:alice",
        )
        # PATCH 仍须成功，尽管记忆失效调用抛错。
        assert resp.code == 0
        assert resp.data["status"] == "archived"

    asyncio.run(scenario())
