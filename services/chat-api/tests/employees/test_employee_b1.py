"""051 B1：数字员工实体 / 可见性 / 档案物化 / 边界交集 / 会话注入。

覆盖范围（``specs/051-digital-employee-profile/tasks.md`` T010 / T014 / T015）：

* 员工 CRUD + 租户隔离 + 软删除（FR-001 / FR-010）；
* 可见性 = 「我的 ∪ 我参与的」（049 口径，FR-005），跨租户 fail-closed；
* 档案物化（引用校验，OQ-2 前显式报错）；
* 会话注入：employee_id 物化快照内嵌会话文档（FR-003）；
* 能力边界与 001 门禁取交集：员工白名单外 Skill / 工具拒绝（FR-002）；
* 未声明员工会话零回归（FR-003 零改动）。

用内存假 DB（同 ``tests/test_portal_requests.py`` 风格），不连真实 Mongo。
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.employees.model import Employee, EmployeeProfile
from app.employees.repository import EmployeeRepository
from app.employees.profile import (
    EmployeeReferenceError,
    materialize_employee_profile,
    validate_employee_references,
)
from app.employees.injection import merge_employee_into_session, employee_profile_from_session
from app.employees.boundary import (
    enforce_employee_skill_boundary,
    enforce_employee_tool_boundary,
    session_employee_profile,
)

TENANT = "tenant-a"
OTHER = "tenant-b"
CREATOR = "user-creator"
MEMBER = "user-member"
OUTSIDER = "user-outsider"


# ---------------------------------------------------------------------------
# 内存假 Mongo（实现本测试用到的操作）
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
                else:  # pragma: no cover - 未实现算子显式报错
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
        self.chat_sessions = self.__getitem__("chat_sessions")

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_employee(db: FakeDB, *, employee_id: str = "emp-1", creator: str = CREATOR, status: str = "active", member_user_ids: list[str] | None = None) -> dict:
    doc = {
        "_id": employee_id,
        "tenant_id": TENANT,
        "name": "财务员工",
        "description": "财务岗位档案",
        "capabilities": {"content_generation": True, "image_generation": False, "code_generation": False, "browser_automation": False, "internal_knowledge": True},
        "tool_access_mode": "selected",
        "tool_ids": ["tool-1"],
        "skill_access_mode": "selected",
        "skill_ids": ["skill-a"],
        "knowledge_base_ids": ["kb-1"],
        "memory_scope": "project",
        "model_config": {"model_instance_id": "model-1"},
        "harness_profile_ref": "",
        "status": status,
        "creator_id": creator,
        "member_user_ids": member_user_ids if member_user_ids is not None else [MEMBER],
        "created_at": _now(),
        "updated_at": _now(),
        "deleted_at": None,
    }
    db["employees"].docs.append(dict(doc))
    return doc


# ---------------------------------------------------------------------------
# 实体 / CRUD / 租户隔离 / 软删除
# ---------------------------------------------------------------------------


def test_employee_visibility_creator_or_member():
    emp = Employee(tenant_id=TENANT, name="财务", creator_id=CREATOR, member_user_ids=[MEMBER])
    assert emp.is_visible_to(CREATOR)
    assert emp.is_visible_to(MEMBER)
    assert not emp.is_visible_to(OUTSIDER)


async def test_repository_create_and_get_tenant_isolated():
    db = FakeDB()
    repo = EmployeeRepository(db)
    doc = await repo.create(TENANT, {"name": "财务员工", "capabilities": {"content_generation": True}}, CREATOR)
    assert doc["_id"]
    got = await repo.get(TENANT, doc["_id"])
    assert got is not None
    assert got["name"] == "财务员工"
    # 跨租户 fail-closed
    assert await repo.get(OTHER, doc["_id"]) is None


async def test_repository_soft_delete_and_list():
    db = FakeDB()
    repo = EmployeeRepository(db)
    doc = await repo.create(TENANT, {"name": "财务员工"}, CREATOR)
    assert len(await repo.list_tenant(TENANT)) == 1
    deleted = await repo.soft_delete(TENANT, doc["_id"], CREATOR)
    assert deleted
    assert len(await repo.list_tenant(TENANT)) == 0
    assert await repo.get(TENANT, doc["_id"]) is None


async def test_repository_list_visible():
    db = FakeDB()
    _seed_employee(db, employee_id="emp-1", creator=CREATOR, member_user_ids=[MEMBER])
    repo = EmployeeRepository(db)
    visible_creator = await repo.list_visible(TENANT, CREATOR)
    visible_member = await repo.list_visible(TENANT, MEMBER)
    visible_outsider = await repo.list_visible(TENANT, OUTSIDER)
    assert len(visible_creator) == 1
    assert len(visible_member) == 1
    assert len(visible_outsider) == 0


async def test_repository_update_status_validation():
    db = FakeDB()
    repo = EmployeeRepository(db)
    doc = await repo.create(TENANT, {"name": "财务员工"}, CREATOR)
    with pytest.raises(ValueError):
        await repo.set_status(TENANT, doc["_id"], "bogus", CREATOR)


# ---------------------------------------------------------------------------
# 档案物化（引用校验 / 快照）
# ---------------------------------------------------------------------------


async def test_validate_employee_references_ok():
    db = FakeDB()
    db.external_tools.docs.append({"_id": "tool-1", "tenant_id": TENANT, "enabled": True})
    db.skills.docs.append({"_id": "skill-a", "tenant_id": TENANT, "enabled": True})
    db.knowledge_documents.docs.append({"_id": "kb-1", "tenant_id": TENANT})
    await validate_employee_references(TENANT, tool_ids=["tool-1"], skill_ids=["skill-a"], knowledge_base_ids=["kb-1"], db=db)


async def test_validate_employee_references_rejects_invalid():
    db = FakeDB()
    db.external_tools.docs.append({"_id": "tool-1", "tenant_id": TENANT, "enabled": True})
    with pytest.raises(EmployeeReferenceError):
        await validate_employee_references(TENANT, tool_ids=["tool-1", "missing-tool"], db=db)


async def test_materialize_employee_profile_none_when_inactive():
    db = FakeDB()
    _seed_employee(db, employee_id="emp-1", status="disabled")
    profile = await materialize_employee_profile(TENANT, "emp-1", db=db)
    assert profile is None


async def test_materialize_employee_profile_ok():
    db = FakeDB()
    _seed_employee(db, employee_id="emp-1")
    db.external_tools.docs.append({"_id": "tool-1", "tenant_id": TENANT, "enabled": True})
    db.skills.docs.append({"_id": "skill-a", "tenant_id": TENANT, "enabled": True})
    db.knowledge_documents.docs.append({"_id": "kb-1", "tenant_id": TENANT})
    profile = await materialize_employee_profile(TENANT, "emp-1", db=db)
    assert profile is not None
    assert profile.employee_id == "emp-1"
    assert profile.allows_skill("skill-a")
    assert not profile.allows_skill("skill-b")


# ---------------------------------------------------------------------------
# 会话注入（FR-003）
# ---------------------------------------------------------------------------


def test_merge_employee_into_session_snapshot():
    profile = EmployeeProfile(
        employee_id="emp-1",
        name="财务员工",
        capabilities={"content_generation": True},
        skill_access_mode="selected",
        skill_ids=["skill-a"],
        knowledge_base_ids=["kb-1"],
        memory_scope="project",
        model_config={"model_instance_id": "model-1"},
    )
    merged = merge_employee_into_session({}, profile)
    assert merged["employee_id"] == "emp-1"
    assert merged["employee_profile"]["employee_id"] == "emp-1"
    assert merged["knowledge_base_ids"] == ["kb-1"]
    assert merged["employee_memory_scope"] == "project"
    assert merged["employee_model_config"]["model_instance_id"] == "model-1"


def test_employee_profile_from_session_roundtrip():
    profile = EmployeeProfile(employee_id="emp-1", skill_access_mode="all", memory_scope="department")
    merged = merge_employee_into_session({}, profile)
    restored = employee_profile_from_session(merged)
    assert restored is not None
    assert restored.employee_id == "emp-1"
    assert restored.memory_scope == "department"


async def test_session_employee_profile_from_store():
    db = FakeDB()
    profile = EmployeeProfile(employee_id="emp-1", skill_access_mode="selected", skill_ids=["skill-a"])
    db.chat_sessions.docs.append({"_id": "sess-1", "employee_profile": profile.to_document()})
    got = await session_employee_profile(db, "sess-1")
    assert got is not None
    assert got.employee_id == "emp-1"


# ---------------------------------------------------------------------------
# 能力边界与 001 门禁取交集（FR-002）
# ---------------------------------------------------------------------------


async def test_employee_skill_boundary_denies_outside_whitelist():
    db = FakeDB()
    profile = EmployeeProfile(employee_id="emp-1", skill_access_mode="selected", skill_ids=["skill-a"])
    db.chat_sessions.docs.append({"_id": "sess-1", "employee_profile": profile.to_document()})
    assert await enforce_employee_skill_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", selected_skill_id="skill-a", db=db)
    assert not await enforce_employee_skill_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", selected_skill_id="skill-b", db=db)


async def test_employee_skill_boundary_noop_without_employee():
    db = FakeDB()
    db.chat_sessions.docs.append({"_id": "sess-1"})
    assert await enforce_employee_skill_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", selected_skill_id="skill-b", db=db)


async def test_employee_tool_boundary_denies_outside_whitelist():
    db = FakeDB()
    profile = EmployeeProfile(employee_id="emp-1", tool_access_mode="selected", tool_ids=["tool-1"])
    db.chat_sessions.docs.append({"_id": "sess-1", "employee_profile": profile.to_document()})
    assert await enforce_employee_tool_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", tool_name="askai_http_tool1", external_tool_id="tool-1", db=db)
    assert not await enforce_employee_tool_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", tool_name="askai_http_tool2", external_tool_id="tool-2", db=db)


async def test_employee_capability_boundary():
    db = FakeDB()
    profile = EmployeeProfile(employee_id="emp-1", capabilities={"internal_knowledge": True, "image_generation": False})
    db.chat_sessions.docs.append({"_id": "sess-1", "employee_profile": profile.to_document()})
    assert await enforce_employee_tool_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", tool_name="knowledge.search", capability_ref="knowledge.search@v1", db=db)
    assert not await enforce_employee_tool_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", tool_name="image.generate", capability_ref="image.generate@v1", db=db)


async def test_audit_written_on_denial():
    db = FakeDB()
    profile = EmployeeProfile(employee_id="emp-1", skill_access_mode="selected", skill_ids=["skill-a"])
    db.chat_sessions.docs.append({"_id": "sess-1", "employee_profile": profile.to_document()})
    await enforce_employee_skill_boundary(tenant_id=TENANT, user_id=MEMBER, session_id="sess-1", selected_skill_id="skill-b", db=db)
    assert len(db["gate_events"].docs) == 1
    assert db["gate_events"].docs[0]["decision"] == "deny"
