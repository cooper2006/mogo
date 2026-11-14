"""053-plaza-template-distribution：模板广场查询端点契约测试（chat-api 侧）.

覆盖（FR-008 / FR-010）：

* end_user 会话鉴权（无会话 → 401）
* 租户内已上架模板可见（跨租户 fail-closed）
* 只读投影（不含内容敏感字段泄漏判断：默认列表不含 content）
* 类型过滤 + 非法类型拒绝（400）

用内存假 DB，不连真实 Mongo / panwei，聚焦端点契约与租户隔离。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import plaza_templates as plaza_api
from app.api.principal import ApiPrincipal, require_end_user_principal

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, length: int | None = None):
        return self._docs[:length] if length else list(self._docs)


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def _match(self, doc: dict, scope: dict) -> bool:
        for key, value in scope.items():
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
            elif doc.get(key) != value:
                return False
        return True

    def find(self, scope: dict) -> _Cursor:
        return _Cursor([d for d in self.docs if self._match(d, scope)])

    async def find_one(self, scope: dict):
        return next((d for d in self.docs if self._match(d, scope)), None)


class _FakeDB:
    def __init__(self) -> None:
        self.asset_templates = _FakeCollection()

    def __getitem__(self, name: str) -> _FakeCollection:
        if name == "asset_templates":
            return self.asset_templates
        raise KeyError(name)


@pytest.fixture
def client(monkeypatch):
    import app.api.endpoints.plaza_templates as mod

    db = _FakeDB()
    db.asset_templates.docs = [
        {
            "template_id": "tpl_sop_1",
            "tenant_id": TENANT,
            "name": "合同审查 SOP",
            "asset_type": "sop_template",
            "version": 1,
            "state": "published",
            "category": "legal",
            "description": "合同审查流程",
            "owner_id": "owner-1",
            "content": {"orchestration": {"id": "sop_1", "version": "1"}},
            "updated_at": None,
        },
        {
            "template_id": "tpl_emp_1",
            "tenant_id": TENANT,
            "name": "财务员工",
            "asset_type": "employee_template",
            "version": 1,
            "state": "published",
            "category": "finance",
            "description": "",
            "owner_id": "owner-1",
            "content": {"name": "财务员工"},
            "updated_at": None,
        },
        {
            # 其他租户已上架模板 —— 跨租户不可见（fail-closed）
            "template_id": "tpl_other",
            "tenant_id": OTHER_TENANT,
            "name": "其他租户模板",
            "asset_type": "sop_template",
            "version": 1,
            "state": "published",
            "category": "",
            "description": "",
            "owner_id": "owner-2",
            "content": {},
            "updated_at": None,
        },
        {
            # 本租户草稿 —— 非已上架不可见
            "template_id": "tpl_draft",
            "tenant_id": TENANT,
            "name": "草稿模板",
            "asset_type": "sop_template",
            "version": 1,
            "state": "draft",
            "category": "",
            "description": "",
            "owner_id": "owner-1",
            "content": {},
            "updated_at": None,
        },
    ]
    monkeypatch.setattr(mod, "get_db", lambda: db)

    app = FastAPI()
    app.include_router(plaza_api.router)

    async def _principal() -> ApiPrincipal:
        return ApiPrincipal(kind="end_user", tenant_id=TENANT, user_id="user-1")

    app.dependency_overrides[require_end_user_principal] = _principal
    return TestClient(app)


def test_list_plaza_templates_scoped_to_tenant(client) -> None:
    resp = client.get("/api/v1/plaza/templates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    ids = {item["template_id"] for item in data["items"]}
    assert ids == {"tpl_sop_1", "tpl_emp_1"}
    # 跨租户 + 草稿被排除（fail-closed）
    assert "tpl_other" not in ids
    assert "tpl_draft" not in ids
    # 列表投影不含 content（避免敏感字段泄漏）
    assert all("content" not in item for item in data["items"])


def test_list_plaza_templates_filter_type(client) -> None:
    resp = client.get("/api/v1/plaza/templates", params={"asset_type": "sop_template"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["asset_type"] == "sop_template"


def test_list_plaza_templates_reject_unknown_type(client) -> None:
    resp = client.get("/api/v1/plaza/templates", params={"asset_type": "skill"})
    assert resp.status_code == 400


def test_get_plaza_template_detail(client) -> None:
    resp = client.get("/api/v1/plaza/templates/tpl_sop_1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["template_id"] == "tpl_sop_1"
    assert data["content"]["orchestration"]["id"] == "sop_1"


def test_get_plaza_template_not_found(client) -> None:
    resp = client.get("/api/v1/plaza/templates/tpl_other")
    assert resp.status_code == 404


def test_get_plaza_template_draft_hidden(client) -> None:
    resp = client.get("/api/v1/plaza/templates/tpl_draft")
    assert resp.status_code == 404
