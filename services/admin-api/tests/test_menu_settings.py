"""055 菜单管理 —— 模型校验、服务存取与端点契约测试。

纯逻辑测试，不依赖真实 MongoDB；db 门面用内存 fake 替换。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes import menu_settings as route_module
from app.menu_settings import service as service_module
from app.menu_settings.models import (
    MenuNode,
    MenuPlanPayload,
    MenuPlanResponse,
    node_from_row,
)
from app.menu_settings.service import MenuSettingsService


class FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.find_filters: list[dict] = []

    @staticmethod
    def _key(flt: dict) -> tuple[str, str]:
        return (str(flt.get("tenant_id")), str(flt.get("scheme_key")))

    async def find_one(self, flt: dict):
        self.find_filters.append(flt)
        return self.rows.get(self._key(flt))

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        row = dict(self.rows.get(self._key(flt), {}))
        row.update(update["$set"])
        if "$setOnInsert" in update and self._key(flt) not in self.rows:
            row.update(update["$setOnInsert"])
        self.rows[self._key(flt)] = row
        return type("Result", (), {"matched_count": 1})()

    async def delete_one(self, flt: dict):
        existed = self.rows.pop(self._key(flt), None)
        return type("Result", (), {"deleted_count": 1 if existed else 0})()


class FakeDB:
    def __init__(self, collection: FakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection


@pytest.fixture
def fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    collection = FakeCollection()
    monkeypatch.setattr(service_module, "get_db", lambda: FakeDB(collection))
    return collection


# --------------------------------------------------------------------------- 模型


def test_menu_node_accepts_absolute_child_path() -> None:
    node = MenuNode(key="/hooks/rules", parentKey="/resources", visible=False)
    assert node.key == "/hooks/rules"
    assert node.visible is False


@pytest.mark.parametrize("key", ["hooks/rules", "/a//b", "/a/../b", "/a b", "", "/a?x=1", "/a#b"])
def test_menu_node_rejects_invalid_key(key: str) -> None:
    with pytest.raises(ValidationError):
        MenuNode(key=key, parentKey="/resources")


def test_menu_node_rejects_unknown_parent_group() -> None:
    with pytest.raises(ValidationError, match="menu_parent_key_not_a_group"):
        MenuNode(key="/evil", parentKey="/not-a-group")


def test_group_node_cannot_have_parent() -> None:
    with pytest.raises(ValidationError, match="menu_group_cannot_have_parent"):
        MenuNode(key="/assets", parentKey="/resources")


def test_menu_node_rejects_unknown_icon() -> None:
    with pytest.raises(ValidationError, match="invalid_menu_icon_key"):
        MenuNode(key="/token-stats", parentKey="/audit", iconKey="<svg onload=alert(1)>")


def test_menu_node_accepts_known_icon() -> None:
    assert MenuNode(key="/token-stats", parentKey="/audit", iconKey="token").iconKey == "token"


def test_menu_node_rejects_unknown_label_locale() -> None:
    with pytest.raises(ValidationError, match="invalid_menu_label_locale"):
        MenuNode(key="/token-stats", parentKey="/audit", label={"fr-FR": "Usage"})


def test_menu_node_accepts_bilingual_label_and_drops_blank() -> None:
    node = MenuNode(
        key="/token-stats", parentKey="/audit",
        label={"zh-CN": " 用量统计 ", "en-US": "   "},
    )
    assert node.label == {"zh-CN": "用量统计"}


def test_locked_node_is_always_visible() -> None:
    node = MenuNode(key="/settings/menus", visible=False)
    assert node.locked is True
    assert node.visible is True


def test_explicit_locked_flag_forces_visible() -> None:
    node = MenuNode(key="/dashboard", locked=True, visible=False)
    assert node.visible is True


def test_plan_rejects_duplicate_keys() -> None:
    with pytest.raises(ValidationError, match="menu_node_keys_must_be_unique"):
        MenuPlanPayload(nodes=[
            {"key": "/skills", "parentKey": "/assets"},
            {"key": "/skills", "parentKey": "/resources"},
        ])


def test_plan_rejects_too_many_nodes() -> None:
    with pytest.raises(ValidationError):
        MenuPlanPayload(nodes=[
            {"key": f"/x/{i}", "parentKey": "/assets"} for i in range(201)
        ])


def test_node_from_row_skips_malformed_data() -> None:
    assert node_from_row({"key": "../evil"}) is None
    assert node_from_row({"key": "/skills", "parentKey": "/assets"}) is not None


# --------------------------------------------------------------------------- service


@pytest.mark.asyncio
async def test_get_plan_without_record_returns_empty_and_does_not_write(fake_collection: FakeCollection) -> None:
    result = await MenuSettingsService().get_plan("tenant-a")
    assert isinstance(result, MenuPlanResponse)
    assert result.nodes == []
    assert result.updatedAt == ""
    assert fake_collection.rows == {}  # GET 无副作用


@pytest.mark.asyncio
async def test_save_plan_scopes_by_tenant(fake_collection: FakeCollection) -> None:
    svc = MenuSettingsService()
    payload = MenuPlanPayload(nodes=[{"key": "/token-stats", "parentKey": "/audit", "visible": False}])
    saved = await svc.save_plan("tenant-a", "admin-1", payload)
    assert saved.nodes[0].key == "/token-stats"
    assert fake_collection.rows[("tenant-a", "default")]["updated_by"] == "admin-1"
    assert ("tenant-b", "default") not in fake_collection.rows
    assert (await svc.get_plan("tenant-b")).nodes == []


@pytest.mark.asyncio
async def test_save_plan_normalizes_locked_and_reads_back(fake_collection: FakeCollection) -> None:
    svc = MenuSettingsService()
    payload = MenuPlanPayload(nodes=[{"key": "/settings/menus", "visible": False}])
    await svc.save_plan("tenant-a", "admin-1", payload)
    row = fake_collection.rows[("tenant-a", "default")]
    assert row["nodes"][0]["visible"] is True
    assert row["nodes"][0]["locked"] is True
    assert (await svc.get_plan("tenant-a")).nodes[0].visible is True


@pytest.mark.asyncio
async def test_get_plan_skips_corrupt_nodes(fake_collection: FakeCollection) -> None:
    fake_collection.rows[("tenant-a", "default")] = {
        "tenant_id": "tenant-a", "scheme_key": "default",
        "nodes": [
            {"key": "/skills", "parentKey": "/assets"},
            {"key": "../evil", "parentKey": "/assets"},
            "not-a-dict",
        ],
    }
    result = await MenuSettingsService().get_plan("tenant-a")
    assert [node.key for node in result.nodes] == ["/skills"]


@pytest.mark.asyncio
async def test_delete_plan_is_idempotent(fake_collection: FakeCollection) -> None:
    svc = MenuSettingsService()
    assert await svc.delete_plan("tenant-a") is True
    await svc.save_plan("tenant-a", "admin-1", MenuPlanPayload(nodes=[]))
    assert await svc.delete_plan("tenant-a") is True
    assert (await svc.get_plan("tenant-a")).nodes == []


# --------------------------------------------------------------------------- 路由契约


@pytest.mark.asyncio
async def test_routes_use_authenticated_tenant_not_request_body(fake_collection: FakeCollection) -> None:
    user = {"tenant_id": "tenant-a", "_id": "admin-1"}
    payload = MenuPlanPayload(
        schemeKey="default",
        nodes=[{"key": "/skills", "parentKey": "/assets", "visible": False}],
    )
    saved = await route_module.save_menu_settings(payload, current_user=user)
    assert saved.nodes[0].visible is False
    assert fake_collection.rows[("tenant-a", "default")]["tenant_id"] == "tenant-a"
    assert fake_collection.rows[("tenant-a", "default")]["updated_by"] == "admin-1"
    loaded = await route_module.get_menu_settings(current_user=user)
    assert loaded.nodes[0].key == "/skills"


@pytest.mark.asyncio
async def test_reset_route_returns_ok(fake_collection: FakeCollection) -> None:
    result = await route_module.reset_menu_settings(current_user={"tenant_id": "tenant-a"})
    assert result.ok is True
    assert result.schemeKey == "default"


def test_router_registers_menu_settings_endpoints() -> None:
    from fastapi import FastAPI

    from app.api.router import api_router

    # FastAPI 0.142 起 include_router 是懒展开，必须借 OpenAPI 生成拿到最终路径，
    # 直接读 api_router.routes 只会看到 _IncludedRouter 包装对象。
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    schema = app.openapi()
    assert "/api/v1/settings/menus" in schema["paths"]
    assert {"get", "put", "delete"} <= set(schema["paths"]["/api/v1/settings/menus"])
