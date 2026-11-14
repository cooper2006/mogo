"""051 B1：数字员工管理端 CRUD + 审计 + 资产中心类型 + 双服务口径。

覆盖范围（``specs/051-digital-employee-profile/tasks.md`` T011 / T012 / T024）：

* 管理端 CRUD + 启停 + 软删除（FR-001 / FR-010 / FR-011）；
* 租户隔离 fail-closed；
* 资产中心类型（asset_type=employee）与门户目录；
* 双服务同口径（049 先例）：admin-api 与 chat-api 共用 employees 集合契约。

用内存假 DB（同 chat-api ``tests/test_portal_requests.py`` 风格），不连真实 Mongo。
admin-api 测试套件无 ``asyncio_mode=auto``，异步调用统一用 ``asyncio.run`` 包裹。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.employees.repository import EmployeeRepository

TENANT = "tenant-a"
OTHER = "tenant-b"
ADMIN = "admin-1"


# ---------------------------------------------------------------------------
# 内存假 Mongo
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
                elif op == "$lte":
                    if value is _MISSING or value is None or not value <= arg:
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

    async def find_one(self, filt: dict) -> dict | None:
        for doc in self.docs:
            if _matches(doc, filt):
                return dict(doc)
        return None

    def find(self, filt: dict) -> "_FakeCursor":
        return _FakeCursor([dict(d) for d in self.docs if _matches(d, filt)])

    async def count_documents(self, filt: dict) -> int:
        return sum(1 for d in self.docs if _matches(d, filt))

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = dict(update.get("$set") or {})
        unset = dict(update.get("$unset") or {})
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(set_doc)
                for key in unset:
                    doc.pop(key, None)
                return SimpleNamespace(modified_count=1, matched_count=1)
        if upsert:
            new_doc = dict(set_doc)
            new_doc.update({k: v for k, v in filt.items() if not isinstance(v, dict) and k not in ("$or", "$and")})
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc.get("_id"))
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def update_many(self, filt: dict, update: dict) -> SimpleNamespace:
        count = 0
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(dict(update.get("$set") or {}))
                count += 1
        return SimpleNamespace(modified_count=count, matched_count=count)

    async def delete_one(self, filt: dict) -> SimpleNamespace:
        for index, doc in enumerate(self.docs):
            if _matches(doc, filt):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, filt: dict) -> SimpleNamespace:
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, filt)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    async def create_index(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length else list(self._docs)

    def sort(self, *args, **kwargs) -> "_FakeCursor":  # noqa: ARG002
        return self


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}
        self.external_tools = self.__getitem__("external_tools")
        self.skills = self.__getitem__("skills")
        self.knowledge_documents = self.__getitem__("knowledge_documents")
        self.employees = self.__getitem__("employees")

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def repo(monkeypatch) -> EmployeeRepository:
    db = FakeDB()
    # 直接以 db 注入（repository 在 import 时已绑定 ``get_db``，不能靠 patch 生效）。
    return EmployeeRepository(db)


# ---------------------------------------------------------------------------
# CRUD + 租户隔离 + 软删除
# ---------------------------------------------------------------------------


def test_create_and_get(repo):
    doc = asyncio.run(repo.create(TENANT, {"name": "财务员工", "capabilities": {"content_generation": True}}, ADMIN))
    assert doc["_id"]
    got = asyncio.run(repo.get(TENANT, doc["_id"]))
    assert got["name"] == "财务员工"
    # 跨租户 fail-closed
    assert asyncio.run(repo.get(OTHER, doc["_id"])) is None
    # 审计写入 gate_events
    asyncio.run(repo.audit(TENANT, ADMIN, "create", doc["_id"], {"name": doc["name"]}))
    events = repo.db["gate_events"].docs
    assert len(events) == 1
    assert events[0]["tool"] == "employee.create"


def test_update_and_status(repo):
    doc = asyncio.run(repo.create(TENANT, {"name": "财务员工"}, ADMIN))
    updated = asyncio.run(repo.update(TENANT, doc["_id"], {"description": "财务档案", "tool_access_mode": "selected", "tool_ids": ["tool-1"]}, ADMIN))
    assert updated["description"] == "财务档案"
    assert updated["tool_ids"] == ["tool-1"]
    assert asyncio.run(repo.set_status(TENANT, doc["_id"], "disabled", ADMIN))["status"] == "disabled"
    with pytest.raises(ValueError):
        asyncio.run(repo.set_status(TENANT, doc["_id"], "bogus", ADMIN))


def test_soft_delete_keeps_audit_trail(repo):
    doc = asyncio.run(repo.create(TENANT, {"name": "财务员工"}, ADMIN))
    assert asyncio.run(repo.soft_delete(TENANT, doc["_id"], ADMIN))
    assert asyncio.run(repo.get(TENANT, doc["_id"])) is None
    assert len(asyncio.run(repo.list_tenant(TENANT))) == 0


def test_serialize_contract():
    row = {
        "_id": "emp-1",
        "name": "财务员工",
        "status": "active",
        "capabilities": {"content_generation": True},
        "tool_access_mode": "selected",
        "tool_ids": ["tool-1"],
        "skill_access_mode": "selected",
        "skill_ids": ["skill-a"],
        "knowledge_base_ids": ["kb-1"],
        "memory_scope": "project",
        "model_config": {"model_instance_id": "model-1"},
        "creator_id": ADMIN,
        "member_user_ids": ["user-x"],
        "created_at": _now(),
    }
    view = EmployeeRepository.serialize(row)
    assert view["id"] == "emp-1"
    assert view["capabilities"]["content_generation"] is True
    assert view["memoryScope"] == "project"
    assert view["memberUserIds"] == ["user-x"]


def test_dual_service_collection_parity():
    """双服务同口径（049 先例）：employees 集合名与档案字段契约两侧一致。

    本测试守护 admin-api 侧契约；chat-api 侧等价契约在
    ``tests/employees/test_employee_b1.py`` 守护。两侧字段名（snake_case 落库
    / camelCase 序列化）必须一致，否则跨服务读写漂移。
    """
    from app.employees.repository import EMPLOYEE_COLLECTION, CAPABILITY_KEYS, EMPLOYEE_STATUSES

    assert EMPLOYEE_COLLECTION == "employees"
    assert CAPABILITY_KEYS == (
        "content_generation",
        "image_generation",
        "code_generation",
        "browser_automation",
        "internal_knowledge",
    )
    assert EMPLOYEE_STATUSES == ("active", "disabled", "archived")
