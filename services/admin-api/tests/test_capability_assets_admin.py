"""045 T1/T2：资产中心 admin 只读能力资产列表接口契约测试。

覆盖（``specs/045-asset-center/tasks.md`` T1 / T2）：

* admin JWT 鉴权（无 bearer token → 401）
* 列表返回结构（``items`` / ``total`` / 字段）
* ``kind`` / ``state`` 过滤

后端契约见 ``services/admin-api/app/api/routes/capability_assets.py`` 的
``admin_router``（``GET /api/v1/capabilities/list``）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_admin_user
from app.api.routes import capability_assets

TENANT = "default"
_MISSING = object()


def _matches(doc: dict, filt: dict) -> bool:
    """Simple equality matcher（本接口只用 kind/state 等值过滤）。"""
    return all(doc.get(key, _MISSING) == value for key, value in filt.items())


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int = 1) -> "_FakeCursor":
        self._docs = sorted(
            self._docs, key=lambda d: str(d.get(key, "")), reverse=(direction == -1)
        )
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length else list(self._docs)


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: list[dict] = []

    def find(self, filt: dict, projection: dict | None = None) -> _FakeCursor:
        matched = [dict(d) for d in self.docs if _matches(d, filt)]
        if projection:
            matched = [
                {k: d[k] for k in projection if projection[k] and k in d} for d in matched
            ]
        return _FakeCursor(matched)


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection(name))

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _seed_asset(
    db: FakeDB,
    *,
    asset_id: str,
    name: str = "",
    kind: str = "rest",
    state: str = "active",
) -> None:
    db["capability_assets"].docs.append(
        {
            "asset_id": asset_id,
            "name": name,
            "kind": kind,
            "state": state,
            "contract": {"input": {}, "output": {}, "errors": {}, "sla": {}},
            "version": 1,
            "owner_role": "",
            "endpoint": "/x",
            "method": "POST",
            "a2a_exposed": False,
            "last_seen_at": None,
            "updated_at": None,
        }
    )


def _build_app(*, override_auth: bool, db: FakeDB | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(capability_assets.admin_router)
    if override_auth:
        app.dependency_overrides[get_current_admin_user] = lambda: {
            "username": "admin",
            "tenant_id": TENANT,
            "role_name": "组织管理员",
            "permission_codes": [],
        }
    return app


@pytest.fixture()
def api(monkeypatch) -> TestClient:
    db = FakeDB()
    _seed_asset(db, asset_id="cap-1", name="内部搜索", kind="mcp", state="active")
    _seed_asset(db, asset_id="cap-2", name="天气查询", kind="rest", state="active")
    _seed_asset(db, asset_id="cap-3", name="旧接口", kind="tool", state="deprecated")
    monkeypatch.setattr(capability_assets, "get_db", lambda: db)
    return TestClient(_build_app(override_auth=True, db=db))


def test_admin_list_requires_auth() -> None:
    """无 bearer token → 401（admin JWT 鉴权生效）。"""
    client = TestClient(_build_app(override_auth=False))
    response = client.get("/capabilities/list")
    assert response.status_code == 401


def test_admin_list_returns_items(api: TestClient) -> None:
    response = api.get("/capabilities/list")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 3
    items = body["data"]["items"]
    assert {i["asset_id"] for i in items} == {"cap-1", "cap-2", "cap-3"}
    # 字段完整（含 kind / last_seen_at / updated_at，方案 §3.1）
    sample = next(i for i in items if i["asset_id"] == "cap-1")
    assert sample["kind"] == "mcp"
    assert "last_seen_at" in sample and "updated_at" in sample
    assert "contract" in sample


def test_admin_list_kind_filter(api: TestClient) -> None:
    response = api.get("/capabilities/list", params={"kind": "mcp"})
    body = response.json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["asset_id"] == "cap-1"


def test_admin_list_state_filter(api: TestClient) -> None:
    response = api.get("/capabilities/list", params={"state": "active"})
    body = response.json()
    assert body["data"]["total"] == 2
    assert {i["asset_id"] for i in body["data"]["items"]} == {"cap-1", "cap-2"}


def test_admin_list_no_results(api: TestClient) -> None:
    response = api.get("/capabilities/list", params={"kind": "connector"})
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []
