"""017 §9.1 —— admin-api 记忆治理端点契约测试（B4 前端 memories.ts 驱动）。

用内存假 Mongo 打桩（monkeypatch ``memories.get_db``），不连真实库。覆盖：
列表分页与 scope 过滤 / 旧 scope 400 / 不可见 404 / 治理动作落 001 审计 /
``project_id="default"`` 排除（N2）/ stats 结构 / 项目名消歧 / 跨租户 fail-closed。

风格对齐 ``tests/test_portal_admin.py``：FakeDB + TestClient +
``dependency_overrides[get_current_admin_user]``。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_admin_user
from app.api.routes import memories

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
BASE = "/api/v1/memories/admin"

_MISSING = object()


# ---------------------------------------------------------------------------
# 内存假 Mongo（支持实现里用到的查询 / 写操作子集）
# ---------------------------------------------------------------------------
def _matches(doc: dict, filt: dict) -> bool:
    for key, cond in filt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$ne":
                    if value is not _MISSING and value == arg:
                        return False
                elif op == "$exists":
                    if bool(arg) != (value is not _MISSING):
                        return False
                elif op == "$gte":
                    if value is _MISSING or value is None or not value >= arg:
                        return False
                elif op == "$lte":
                    if value is _MISSING or value is None or not value <= arg:
                        return False
                else:  # pragma: no cover - 实现未用到
                    raise AssertionError(f"unsupported operator: {op}")
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, name: str = "") -> None:
        self.name = name
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
        return _FakeCursor([dict(d) for d in self.docs if _matches(doc=d, filt=filt)])

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = dict(update.get("$set") or {})
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(set_doc)
                return SimpleNamespace(modified_count=1, matched_count=1)
        if upsert:
            new_doc = dict(set_doc)
            new_doc.update(
                {k: v for k, v in filt.items() if not isinstance(v, dict) and k != "$or"}
            )
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc.get("_id"))
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def delete_one(self, filt: dict) -> SimpleNamespace:
        for index, doc in enumerate(self.docs):
            if _matches(doc, filt):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length else list(self._docs)


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection(name))


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------
def _user(username: str = "admin", *, role: str = "full_access_admin", codes=None, tenant: str = TENANT) -> dict:
    return {
        "username": username,
        "tenant_id": tenant,
        "role_name": role,
        "permission_codes": list(codes or []),
        "display_name": username,
    }


def _memory(memory_id: str, **overrides) -> dict:
    doc = {
        "memory_id": memory_id,
        "tenant_id": TENANT,
        "scope": "personal",
        "owner_id": "u1",
        "project_id": "",
        "project_owner_id": "",
        "department_id": "",
        "content": f"正文-{memory_id}",
        "l0_summary": f"摘要-{memory_id}",
        "l1_overview": f"概览-{memory_id}",
        "l2_raw": f"原文-{memory_id}",
        "tierable": True,
        "source_session_id": "s1",
        "source_type": "session",
        "archived": False,
        "created_at": time.time() - 3600,
        "last_accessed_at": time.time() - 3600,
    }
    doc.update(overrides)
    return doc


@pytest.fixture()
def api(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(memories, "get_db", lambda: db)

    # 合法（治理可见）记录
    for i in range(5):
        db[memories.MEMORIES_COLLECTION].docs.append(
            _memory(f"p{i}", created_at=time.time() - i * 3600, content=f"周报-{i}")
        )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("proj1", scope="project", project_id="p1", project_owner_id="u1")
    )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("dep1", scope="department", department_id="d1", created_at=time.time() - 8 * 86400)
    )
    db[memories.MEMORIES_COLLECTION].docs.append(_memory("arch1", archived=True))

    # 不可见记录（治理路径应全部 404 / 不出现在列表）
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("legacy_workspace", scope="workspace")
    )
    db[memories.MEMORIES_COLLECTION].docs.append(_memory("legacy_org", scope="org"))
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("default_proj", scope="project", project_id="default", project_owner_id="u1")
    )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("cross_tenant", tenant_id=OTHER_TENANT)
    )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("no_project_owner", scope="project", project_id="p1", project_owner_id="")
    )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("no_department", scope="department", department_id="")
    )
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("no_owner", scope="personal", owner_id="")
    )

    # 049 projects（消歧用）；org_units（提升目标部门存在性）
    db[memories.PROJECTS_COLLECTION].docs.append(
        {"_id": "p1", "tenant_id": TENANT, "user_id": "u1", "title": "项目一"}
    )
    db["org_units"].docs.append({"_id": "d1", "tenant_id": TENANT})

    app = FastAPI()
    app.include_router(memories.router, prefix=BASE)
    holder = {"user": _user()}
    app.dependency_overrides[get_current_admin_user] = lambda: holder["user"]
    client = TestClient(app)
    client.holder = holder  # type: ignore[attr-defined]
    return client, db


# ---------------------------------------------------------------------------
# 1. 列表分页与 scope 过滤
# ---------------------------------------------------------------------------
def test_list_pagination_and_scope_filter(api):
    client, _db = api
    resp = client.get(BASE, params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"items", "total", "page", "page_size"}
    assert body["page"] == 1 and body["page_size"] == 2
    assert len(body["items"]) == 2
    # 8 条治理可见（5 personal + 1 project + 1 department + 1 archived）
    assert body["total"] == 8

    page2 = client.get(BASE, params={"page": 2, "page_size": 2}).json()
    assert len(page2["items"]) == 2
    assert page2["items"][0]["memory_id"] != body["items"][0]["memory_id"]

    proj = client.get(BASE, params={"scope": "project"}).json()
    assert proj["total"] == 1
    assert proj["items"][0]["memory_id"] == "proj1"
    assert proj["items"][0]["project_name"] == "项目一"

    dep = client.get(BASE, params={"scope": "department"}).json()
    assert dep["total"] == 1
    assert dep["items"][0]["memory_id"] == "dep1"

    archived = client.get(BASE, params={"status": "archived"}).json()
    assert archived["total"] == 1
    assert archived["items"][0]["memory_id"] == "arch1"

    keyword = client.get(BASE, params={"keyword": "周报-3"}).json()
    assert keyword["total"] == 1
    assert keyword["items"][0]["memory_id"] == "p3"


def test_list_cross_tenant_filter_returns_empty(api):
    client, _db = api
    # 客户端自报其它租户 → 空结果，不泄露其它租户是否存在
    body = client.get(BASE, params={"tenant_id": OTHER_TENANT}).json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}
    # 同租户筛选正常
    assert client.get(BASE, params={"tenant_id": TENANT}).json()["total"] == 8


# ---------------------------------------------------------------------------
# 2. 旧 scope → 400 scope_invalid（D4 无兼容层）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["workspace", "org", "whatever", "WORKSPACE"])
def test_legacy_scope_returns_400(api, bad):
    client, _db = api
    resp = client.get(BASE, params={"scope": bad})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "scope_invalid"


def test_valid_scope_values_pass(api):
    client, _db = api
    for value in ("personal", "project", "department"):
        assert client.get(BASE, params={"scope": value}).status_code == 200


# ---------------------------------------------------------------------------
# 3. 不可见一律 404（不泄露内容）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "memory_id",
    [
        "legacy_workspace",   # 旧 scope
        "legacy_org",         # 旧 scope
        "default_proj",       # N2
        "cross_tenant",       # 跨租户
        "no_project_owner",   # N1 结构不良
        "no_department",      # 结构不良
        "no_owner",           # 结构不良
        "does-not-exist",     # 不存在
    ],
)
def test_invisible_detail_returns_404(api, memory_id):
    client, _db = api
    resp = client.get(f"{BASE}/{memory_id}")
    assert resp.status_code == 404
    # 404 响应不得回显任何记忆内容
    assert "正文" not in resp.text


def test_invisible_records_absent_from_list(api):
    client, _db = api
    ids = {item["memory_id"] for item in client.get(BASE).json()["items"]}
    assert {
        "legacy_workspace", "legacy_org", "default_proj", "cross_tenant",
        "no_project_owner", "no_department", "no_owner",
    }.isdisjoint(ids)


def test_visible_detail_fields_and_audit(api):
    client, db = api
    resp = client.get(f"{BASE}/proj1")
    assert resp.status_code == 200
    item = resp.json()
    assert item["memory_id"] == "proj1"
    assert {"l0_summary", "l1_overview", "l2_raw", "provenance", "project_id", "project_owner_id"} <= set(item)
    assert item["project_name"] == "项目一"
    # 治理接口跨范围查看落管理审计
    views = [d for d in db["system_audit_logs"].docs if d.get("action") == "view"]
    assert len(views) == 1
    assert views[0]["tenant_id"] == TENANT
    assert views[0]["target"] == "proj1"


def test_missing_project_name_shows_archived_label(api):
    client, db = api
    db[memories.MEMORIES_COLLECTION].docs.append(
        _memory("proj_missing", scope="project", project_id="p-x", project_owner_id="u1")
    )
    item = client.get(f"{BASE}/proj_missing").json()
    assert item["project_name"] == "已归档 / 已删除"


# ---------------------------------------------------------------------------
# 4. 治理动作落 001 审计（position_role_audit_logs / feature.audit）
# ---------------------------------------------------------------------------
def _audit_events(db) -> list[str]:
    return [
        row["details"]["event"]
        for row in db["position_role_audit_logs"].docs
        if row.get("action") == "feature.audit" and row.get("target_id") == "017"
    ]


def test_archive_restore_delete_write_audit(api):
    client, db = api
    assert client.post(f"{BASE}/p0/archive", json={"reason": "过期"}).status_code == 200
    assert client.post(f"{BASE}/p0/restore", json={"reason": "误操作"}).status_code == 200
    assert client.request("DELETE", f"{BASE}/p0", json={"reason": "合规"}).status_code == 200

    assert _audit_events(db) == ["memory.archived", "memory.restored", "memory.deleted"]
    for row in db["position_role_audit_logs"].docs:
        assert row["tenant_id"] == TENANT
        assert row["action"] == "feature.audit"
        assert row["details"]["feature"] == "017"
        assert row["details"]["memory_id"] == "p0"
    # delete 真正移除文档
    assert all(d["memory_id"] != "p0" for d in db[memories.MEMORIES_COLLECTION].docs)


def test_archive_sets_archived_flag(api):
    client, db = api
    client.post(f"{BASE}/p0/archive", json={"reason": "r"})
    row = next(d for d in db[memories.MEMORIES_COLLECTION].docs if d["memory_id"] == "p0")
    assert row["archived"] is True
    client.post(f"{BASE}/p0/restore", json={"reason": "r"})
    assert row["archived"] is False


def test_approval_promotes_and_writes_audit(api):
    client, db = api
    resp = client.post(
        f"{BASE}/approvals",
        json={"memory_id": "proj1", "target_scope": "department", "department_id": "d1", "reason": "共享"},
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "department"
    assert resp.json()["department_id"] == "d1"
    assert _audit_events(db) == ["memory.promoted"]
    row = next(d for d in db[memories.MEMORIES_COLLECTION].docs if d["memory_id"] == "proj1")
    assert row["scope"] == "department"
    # G4：分层字段 / provenance / project_owner_id 不丢失
    assert row["l0_summary"] and row["project_owner_id"] == "u1"


def test_approval_unknown_department_returns_404(api):
    client, db = api
    resp = client.post(
        f"{BASE}/approvals",
        json={"memory_id": "proj1", "target_scope": "department", "department_id": "not-exist"},
    )
    assert resp.status_code == 404
    assert db["position_role_audit_logs"].docs == []


def test_policies_put_writes_audit_and_roundtrip(api):
    client, db = api
    defaults = client.get(f"{BASE}/policies").json()
    assert defaults["decay_days"] == 30
    assert defaults["cleanup_policy"] == "archive"

    payload = {**defaults, "decay_days": 15, "cleanup_policy": "delete"}
    resp = client.put(f"{BASE}/policies", json=payload)
    assert resp.status_code == 200
    assert resp.json()["decay_days"] == 15
    assert client.get(f"{BASE}/policies").json()["decay_days"] == 15
    assert _audit_events(db) == ["memory.policy.updated"]


def test_governance_action_on_invisible_is_404_without_audit(api):
    client, db = api
    assert client.post(f"{BASE}/default_proj/archive", json={"reason": "r"}).status_code == 404
    assert client.request("DELETE", f"{BASE}/cross_tenant", json={"reason": "r"}).status_code == 404
    assert db["position_role_audit_logs"].docs == []


# ---------------------------------------------------------------------------
# 5. project_id == "default" 不得作为项目记忆展示 / 治理放行（N2）
# ---------------------------------------------------------------------------
def test_default_project_excluded(api):
    client, db = api
    body = client.get(BASE, params={"scope": "project"}).json()
    assert body["total"] == 1
    assert body["items"][0]["memory_id"] == "proj1"
    assert client.get(f"{BASE}/default_proj").status_code == 404
    assert client.post(f"{BASE}/default_proj/archive", json={"reason": "r"}).status_code == 404
    assert db["position_role_audit_logs"].docs == []


# ---------------------------------------------------------------------------
# 6. stats 结构
# ---------------------------------------------------------------------------
def test_stats_structure(api):
    client, _db = api
    resp = client.get(f"{BASE}/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert set(stats) >= {"total", "by_scope", "recent_added", "pending_approval"}
    assert stats["total"] == 8
    assert set(stats["by_scope"]) == {"personal", "project", "department"}
    assert stats["by_scope"] == {"personal": 6, "project": 1, "department": 1}
    assert stats["recent_added"] == 7  # dep1 是 8 天前，其余 7 条在 7 天内
    assert stats["pending_approval"] == 0
    assert isinstance(stats.get("department_coverage"), int)
    assert isinstance(stats.get("pending_decay_archive"), int)


# ---------------------------------------------------------------------------
# 补充：权限码 / project_owner_id 只读回显
# ---------------------------------------------------------------------------
def test_manage_requires_permission(api):
    client, _db = api
    client.holder["user"] = _user(role="组织管理员")  # 只有 memory:read 基线
    assert client.get(BASE).status_code == 200
    assert client.post(f"{BASE}/p0/archive", json={"reason": "r"}).status_code == 403


def test_client_project_owner_id_is_ignored(api):
    client, db = api
    resp = client.post(
        f"{BASE}/proj1/archive",
        json={"reason": "r", "project_owner_id": "attacker"},
    )
    assert resp.status_code == 200
    row = next(d for d in db[memories.MEMORIES_COLLECTION].docs if d["memory_id"] == "proj1")
    assert row["project_owner_id"] == "u1"


# ---------------------------------------------------------------------------
# 7. 契约 §响应回显：actual_scope / resolved_from 现算（恒缺修复）
# ---------------------------------------------------------------------------
_RESOLVED_FROM_ENUM = {"explicit", "default", "default_fallback", "sediment"}


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"source_type": "session"}, "sediment"),
        ({"source_type": "", "project_id": "default", "scope": "personal"}, "default_fallback"),
        ({"source_type": "", "scope": "personal", "project_id": "", "department_id": ""}, "default"),
        ({"source_type": "", "scope": "project", "project_id": "p1", "project_owner_id": "u1"}, "explicit"),
        ({"source_type": "", "scope": "department", "department_id": "d1"}, "explicit"),
    ],
)
def test_serialize_computes_resolved_from(overrides, expected):
    """_serialize 按 chat-api 端点同款规则现算 4 个枚举，无 legacy_alias。"""
    item = memories._serialize(_memory("m-x", **overrides))
    assert item["resolved_from"] == expected
    assert item["resolved_from"] in _RESOLVED_FROM_ENUM
    assert item["resolved_from"] != "legacy_alias"


def test_serialize_actual_scope_is_computed_not_from_db():
    """store.py 不落库这两字段：DB 里伪造的值不被采信，一律现算回显。"""
    doc = _memory(
        "m-x",
        scope="personal",
        source_type="",
        actual_scope="department",
        resolved_from="legacy_alias",
    )
    item = memories._serialize(doc)
    assert item["actual_scope"] == "personal"
    assert item["resolved_from"] == "default"
    assert "legacy_alias" not in item.values()
    # project_owner_id 仍为只读回显，不凭空编造。
    assert item["project_owner_id"] == ""


def test_list_and_detail_echo_resolved_from_actual_scope(api):
    """治理端列表 / 详情逐条恒回显 actual_scope / resolved_from（此前恒缺）。"""
    client, _db = api
    body = client.get(BASE).json()
    assert body["items"]
    for item in body["items"]:
        assert item["actual_scope"] == item["scope"]
        assert item["resolved_from"] in _RESOLVED_FROM_ENUM
        assert "project_owner_id" in item

    detail = client.get(f"{BASE}/p0").json()
    assert detail["actual_scope"] == "personal"
    assert detail["resolved_from"] == "sediment"  # fixture 默认 source_type=session
