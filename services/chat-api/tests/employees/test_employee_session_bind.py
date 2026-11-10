"""051 T027：会话发起→员工注入链路（``_bind_session_employee`` 集成级）。

覆盖 SC-001 的会话发起环节（spec 的 US2 / FR-003）：

* 员工已认领（创建者可见）→ 会话注入 employee_profile / knowledge_base_ids /
  memory_scope / model_config 快照；
* 员工不可见 → 404 fail-closed（不泄露存在性）；
* 员工非 active → 409；
* 档案引用失效 → 422（OQ-2 显式报错）。

用内存假 DB + monkeypatch ``get_db``（repository / profile / sessions 三处），
不连真实 Mongo，不依赖完整运行栈。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.endpoints.sessions import _bind_session_employee

TENANT = "tenant-a"
CREATOR = "user-creator"
OUTSIDER = "user-outsider"
EMPLOYEE = "emp-1"


# ---------------------------------------------------------------------------
# 内存假 Mongo（本测试用到的操作）
# ---------------------------------------------------------------------------
_MISSING = object()


def _matches(doc: dict, filt: dict) -> bool:
    for key, cond in filt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$exists":
                    if bool(arg) != (value is not _MISSING):
                        return False
                elif op == "$ne":
                    if value is not _MISSING and value == arg:
                        return False
                else:  # pragma: no cover
                    raise AssertionError(op)
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def find_one(self, filt: dict, projection: dict | None = None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, filt):
                out = dict(doc)
                if projection:
                    out = {k: v for k, v in out.items() if k in projection}
                return out
        return None

    async def count_documents(self, filt: dict) -> int:
        return sum(1 for d in self.docs if _matches(d, filt))

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = dict(update.get("$set") or {})
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(set_doc)
                return SimpleNamespace(modified_count=1, matched_count=1)
        if upsert:
            new_doc = dict(set_doc)
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc.get("_id"))
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def create_index(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}
        self.external_tools = self.__getitem__("external_tools")
        self.skills = self.__getitem__("skills")
        self.knowledge_documents = self.__getitem__("knowledge_documents")
        self.chat_sessions = self.__getitem__("chat_sessions")

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _seed_employee(db: FakeDB, *, status: str = "active", creator: str = CREATOR) -> None:
    db["employees"].docs.append({
        "_id": EMPLOYEE,
        "tenant_id": TENANT,
        "name": "财务员工",
        "description": "财务档案",
        "status": status,
        "creator_id": creator,
        "member_user_ids": [],
        "deleted_at": None,
        "capabilities": {"content_generation": True, "image_generation": False},
        "tool_access_mode": "selected",
        "tool_ids": [],
        "skill_access_mode": "all",
        "skill_ids": [],
        "knowledge_base_ids": ["kb-1"],
        "memory_scope": "project",
        "model_config": {"model": "gpt-4o"},
        "harness_profile_ref": "",
    })


def _seed_kb(db: FakeDB) -> None:
    db.knowledge_documents.docs.append({"_id": "kb-1", "tenant_id": TENANT})


@pytest.fixture
def fake_db(monkeypatch) -> FakeDB:
    db = FakeDB()
    import app.employees.repository as repo_mod
    import app.employees.profile as profile_mod
    import app.api.endpoints.sessions as sessions_mod

    monkeypatch.setattr(repo_mod, "get_db", lambda: db)
    monkeypatch.setattr(profile_mod, "get_db", lambda: db)
    monkeypatch.setattr(sessions_mod, "get_db", lambda: db)
    return db


# ---------------------------------------------------------------------------
# 会话发起注入
# ---------------------------------------------------------------------------

async def test_bind_session_injects_employee_profile(fake_db):
    _seed_employee(fake_db)
    _seed_kb(fake_db)
    merged = await _bind_session_employee(
        {"_id": "sess-1", "user_id": CREATOR},
        user_id=CREATOR, tenant_id=TENANT, employee_id=EMPLOYEE,
    )
    assert merged["employee_id"] == EMPLOYEE
    profile = merged["employee_profile"]
    assert profile["employee_id"] == EMPLOYEE
    assert profile["name"] == "财务员工"
    assert profile["memory_scope"] == "project"
    assert profile["knowledge_base_ids"] == ["kb-1"]
    assert profile["model_config"] == {"model": "gpt-4o"}
    assert merged["employee_memory_scope"] == "project"
    assert merged["knowledge_base_ids"] == ["kb-1"]


async def test_bind_session_not_visible_404(fake_db):
    _seed_employee(fake_db)
    _seed_kb(fake_db)
    with pytest.raises(HTTPException) as exc:
        await _bind_session_employee(
            {"_id": "sess-1", "user_id": OUTSIDER},
            user_id=OUTSIDER, tenant_id=TENANT, employee_id=EMPLOYEE,
        )
    assert exc.value.status_code == 404


async def test_bind_session_not_active_409(fake_db):
    _seed_employee(fake_db, status="disabled")
    _seed_kb(fake_db)
    with pytest.raises(HTTPException) as exc:
        await _bind_session_employee(
            {"_id": "sess-1", "user_id": CREATOR},
            user_id=CREATOR, tenant_id=TENANT, employee_id=EMPLOYEE,
        )
    assert exc.value.status_code == 409


async def test_bind_session_reference_invalid_422(fake_db):
    # 员工引用 kb-1 但知识库不存在 → 引用失效显式报错（OQ-2）。
    _seed_employee(fake_db)
    with pytest.raises(HTTPException) as exc:
        await _bind_session_employee(
            {"_id": "sess-1", "user_id": CREATOR},
            user_id=CREATOR, tenant_id=TENANT, employee_id=EMPLOYEE,
        )
    assert exc.value.status_code == 422


async def test_bind_session_missing_employee_404(fake_db):
    with pytest.raises(HTTPException) as exc:
        await _bind_session_employee(
            {"_id": "sess-1", "user_id": CREATOR},
            user_id=CREATOR, tenant_id=TENANT, employee_id=EMPLOYEE,
        )
    assert exc.value.status_code == 404
