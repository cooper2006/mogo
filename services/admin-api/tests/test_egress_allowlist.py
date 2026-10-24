"""038 egress sandbox — admin allowlist store + route tests.

Covers the admin-api half of 038: per-tenant CRUD over ``egress_allowlist``,
tenant isolation, platform-entry write authority, and the read-only egress log
query. No Mongo: the store runs in its in-memory mode and the router is mounted
with a stubbed ``get_egress_admin``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import egress as egress_routes
from app.services.egress_store import EgressAllowlistStore, RuleValidationError

TENANT_ID = "t-1"
OTHER_TENANT = "t-2"


# ---------------------------------------------------------------------------
# Store (in-memory)
# ---------------------------------------------------------------------------


def test_create_and_get_tenant_entry() -> None:
    store = EgressAllowlistStore()
    created = __import__("asyncio").run(
        store.create(scope="tenant", match_domain="Example.COM.", tenant_id=TENANT_ID)
    )
    assert created.scope == "tenant"
    assert created.match_domain == "example.com"  # 归一化
    assert __import__("asyncio").run(store.get(created.entry_id)) is not None


def test_create_platform_entry() -> None:
    store = EgressAllowlistStore()
    created = __import__("asyncio").run(store.create(scope="platform", match_domain="openai.com"))
    assert created.scope == "platform"
    assert created.tenant_id == ""


def test_list_visible_scopes_tenant_view() -> None:
    store = EgressAllowlistStore()
    __import__("asyncio").run(store.create(scope="platform", match_domain="openai.com"))
    __import__("asyncio").run(store.create(scope="tenant", match_domain="a.com", tenant_id=TENANT_ID))
    __import__("asyncio").run(store.create(scope="tenant", match_domain="b.com", tenant_id=OTHER_TENANT))
    visible = __import__("asyncio").run(store.list_visible(TENANT_ID))
    domains = {e.match_domain for e in visible}
    assert domains == {"openai.com", "a.com"}  # 平台 + 本租户，跨租户不可见


def test_update_and_delete() -> None:
    store = EgressAllowlistStore()
    created = __import__("asyncio").run(store.create(scope="tenant", match_domain="a.com", tenant_id=TENANT_ID))
    updated = __import__("asyncio").run(store.update(created.entry_id, enabled=False, path_prefix="/v1"))
    assert updated.enabled is False
    assert updated.path_prefix == "v1"  # 归一化
    assert __import__("asyncio").run(store.delete(created.entry_id)) is True
    assert __import__("asyncio").run(store.get(created.entry_id)) is None


def test_seed_platform_defaults_is_idempotent() -> None:
    store = EgressAllowlistStore()
    first = __import__("asyncio").run(store.seed_platform_defaults())
    second = __import__("asyncio").run(store.seed_platform_defaults())
    assert first and second
    # 幂等：第二次不再新增
    assert len(second) == len(first)


def test_validation_rejects_bad_domains() -> None:
    store = EgressAllowlistStore()
    for bad in ["https://example.com", "example.com/path", "user@example.com", "127.0.0.1", ""]:
        try:
            __import__("asyncio").run(
                store.create(scope="tenant", match_domain=bad, tenant_id=TENANT_ID)
            )
        except RuleValidationError:
            continue
        raise AssertionError(f"expected RuleValidationError for match_domain={bad!r}")


def test_validation_requires_tool_id_for_tool_scope() -> None:
    store = EgressAllowlistStore()
    try:
        __import__("asyncio").run(store.create(scope="tool", match_domain="a.com", tenant_id=TENANT_ID))
    except RuleValidationError:
        return
    raise AssertionError("expected RuleValidationError for tool scope without tool_id")


def test_validation_rejects_invalid_scope() -> None:
    store = EgressAllowlistStore()
    try:
        __import__("asyncio").run(store.create(scope="global", match_domain="a.com", tenant_id=TENANT_ID))
    except RuleValidationError:
        return
    raise AssertionError("expected RuleValidationError for unknown scope")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _mount_client(monkeypatch, user: dict, shared_store: EgressAllowlistStore) -> TestClient:
    app = FastAPI()
    # 与 app/main.py 一致：api_router 挂 /api。
    app.include_router(egress_routes.router, prefix="/api")

    async def fake_admin(_authorization=None):
        return user

    app.dependency_overrides[egress_routes.get_egress_admin] = fake_admin
    # 让每个请求共享同一个内存 store（真实环境 store 走 Mongo，天然持久）。
    monkeypatch.setattr(egress_routes, "_store", lambda _user: shared_store)
    return TestClient(app)


def test_tenant_admin_crud_flow(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    client = _mount_client(monkeypatch, {"tenant_id": TENANT_ID}, shared)

    created = client.post(
        "/api/egress/allowlist",
        json={"scope": "tenant", "match_domain": "api.example.com", "path_prefix": "/v1", "note": "n"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["tenant_id"] == TENANT_ID
    entry_id = body["entry_id"]

    listed = client.get("/api/egress/allowlist")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] >= 1
    assert any(item["match_domain"] == "api.example.com" for item in payload["items"])

    patched = client.patch(f"/api/egress/allowlist/{entry_id}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    deleted = client.delete(f"/api/egress/allowlist/{entry_id}")
    assert deleted.status_code == 204
    assert client.get("/api/egress/allowlist").json()["total"] >= 0


def test_tenant_admin_cannot_write_platform_entries(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    client = _mount_client(monkeypatch, {"tenant_id": TENANT_ID}, shared)
    response = client.post("/api/egress/allowlist", json={"scope": "platform", "match_domain": "openai.com"})
    assert response.status_code == 403


def test_tenant_admin_sees_platform_defaults(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    __import__("asyncio").run(shared.seed_platform_defaults())
    client = _mount_client(monkeypatch, {"tenant_id": TENANT_ID}, shared)
    payload = client.get("/api/egress/allowlist?scope=platform").json()
    assert payload["total"] >= 1
    assert all(item["scope"] == "platform" for item in payload["items"])


def test_platform_admin_can_write_platform_entries(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    client = _mount_client(monkeypatch, {"tenant_id": "__platform__"}, shared)
    response = client.post("/api/egress/allowlist", json={"scope": "platform", "match_domain": "new.provider.com"})
    assert response.status_code == 201
    assert response.json()["tenant_id"] == ""
    # 平台管理员写 tenant 条目应被拒。
    denied = client.post("/api/egress/allowlist", json={"scope": "tenant", "match_domain": "a.com"})
    assert denied.status_code == 403


def test_platform_admin_can_remove_platform_entry(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    created = __import__("asyncio").run(shared.create(scope="platform", match_domain="openai.com"))
    client = _mount_client(monkeypatch, {"tenant_id": "__platform__"}, shared)
    assert client.delete(f"/api/egress/allowlist/{created.entry_id}").status_code == 204


def test_invalid_entry_shape_is_400(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    client = _mount_client(monkeypatch, {"tenant_id": TENANT_ID}, shared)
    response = client.post("/api/egress/allowlist", json={"scope": "tenant", "match_domain": "https://x.com"})
    assert response.status_code == 400


def test_logs_returns_envelope(monkeypatch) -> None:
    shared = EgressAllowlistStore()
    client = _mount_client(monkeypatch, {"tenant_id": TENANT_ID}, shared)
    # 全量顺序下前面的测试文件会初始化 app.core.db._db（motor 句柄绑定到
    # 已关闭的 asyncio.run() 事件循环），此时 get_db() 正常返回、但后续
    # collection.find() 抛 "Event loop is closed"。本用例只验证信封形状，
    # 显式 stub 掉 get_db，保持"无 DB -> 空信封"的确定语义。
    def _no_db():
        raise RuntimeError("no db in unit test")

    monkeypatch.setattr(egress_routes, "get_db", _no_db)
    # 无 Mongo 时返回空信封，不影响调用方。
    payload = client.get("/api/egress/logs?page=1&page_size=20").json()
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["total"] == 0
