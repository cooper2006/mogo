"""Regression tests for the bootstrap wizard refactor (feature 020).

Originally created in Phase 1 for the (now removed) tenant-creating
``POST /api/setup/initialize``. Under the platform model the wizard only creates
the **platform super-admin** (``POST /api/setup/platform-admin``), so the route
tests below target that endpoint while the ``provision_tenant`` unit tests are
retained. (File name kept for history; a rename would require deleting it.)

Tracks:
* setup_platform_admin creates the platform admin, marks the bootstrap complete
  and always releases the lock;
* 409 when a platform admin already exists, without touching the lock;
* 409 when the bootstrap lock is held;
* any failure still releases the lock;
* provision_tenant skips employee/model/quota/external_search blocks when they
  are omitted (Phase 2, T005) yet still registers a tenants record.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routes import setup as setup_route
from app.api.routes.setup import SetupModelRequest, SetupPlatformAdminRequest
from app.services import tenant_provisioning
from app.services.setup_model import SetupModelError
from app.services.tenant_provisioning import ProvisionResult


def _model(capability: str = "chat") -> SetupModelRequest:
    return SetupModelRequest(
        providerId="openai",
        displayName="GPT",
        modelName="gpt-4o",
        baseUrl="https://api.openai.com/v1",
        apiKey="sk-test-1234567890",
        capability=capability,
    )


def _platform_payload(**overrides: object) -> SetupPlatformAdminRequest:
    base: dict[str, object] = dict(
        username="platform",
        password="platformpass123",
        displayName="平台管理员",
    )
    base.update(overrides)
    return SetupPlatformAdminRequest(**base)  # type: ignore[arg-type]


def _patch_platform_route(monkeypatch, *, exists: bool = False, lock: bool = True, ensure_side_effect=None):
    mocks: dict[str, AsyncMock] = {}
    mocks["ensure_indexes"] = AsyncMock()
    mocks["platform_admin_exists"] = AsyncMock(return_value=exists)
    mocks["_ensure_setup_open"] = AsyncMock()
    mocks["acquire_setup_lock"] = AsyncMock(return_value=lock)
    mocks["release_setup_lock"] = AsyncMock()
    mocks["mark_platform_admin_created"] = AsyncMock()
    if ensure_side_effect is not None:
        mocks["ensure_platform_admin"] = AsyncMock(side_effect=ensure_side_effect)
    else:
        mocks["ensure_platform_admin"] = AsyncMock(return_value={"_id": "platform-oid"})
    for name, mock in mocks.items():
        monkeypatch.setattr(setup_route, name, mock)
    return mocks


def test_platform_admin_creates_and_marks_completed(monkeypatch) -> None:
    mocks = _patch_platform_route(monkeypatch)
    payload = _platform_payload()

    result = asyncio.run(setup_route.setup_platform_admin(payload))

    assert result == {"completed": True, "mainId": "__platform__", "username": "platform"}
    assert mocks["ensure_platform_admin"].call_args.kwargs == {
        "username": "platform",
        "password": "platformpass123",
        "display_name": "平台管理员",
    }
    lock_token = mocks["acquire_setup_lock"].call_args.args[0]
    marked = mocks["mark_platform_admin_created"].call_args.kwargs
    assert marked["lock_token"] == lock_token
    assert marked["username"] == "platform"
    assert marked["display_name"] == "平台管理员"
    mocks["release_setup_lock"].assert_awaited_once_with(lock_token)


def test_platform_admin_conflict_when_already_exists(monkeypatch) -> None:
    mocks = _patch_platform_route(monkeypatch, exists=True)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(setup_route.setup_platform_admin(_platform_payload()))
    assert exc_info.value.status_code == 409  # type: ignore[attr-defined]
    mocks["acquire_setup_lock"].assert_not_awaited()
    mocks["ensure_platform_admin"].assert_not_awaited()


def test_platform_admin_lock_conflict_returns_409(monkeypatch) -> None:
    mocks = _patch_platform_route(monkeypatch, lock=False)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(setup_route.setup_platform_admin(_platform_payload()))
    assert exc_info.value.status_code == 409  # type: ignore[attr-defined]
    mocks["ensure_platform_admin"].assert_not_awaited()
    mocks["release_setup_lock"].assert_not_awaited()


def test_platform_admin_failure_releases_lock(monkeypatch) -> None:
    mocks = _patch_platform_route(monkeypatch, ensure_side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        asyncio.run(setup_route.setup_platform_admin(_platform_payload()))
    mocks["release_setup_lock"].assert_awaited_once()
    mocks["mark_platform_admin_created"].assert_not_awaited()


# ---- provision_tenant unit tests (Phase 2, T005) ----


class _FakeCollection:
    def __init__(self) -> None:
        self.last_update = None

    async def find_one(self, flt=None, projection=None):
        # The only truthy lookup provision_tenant needs is the root department.
        if isinstance(flt, dict) and flt.get("code") == "root":
            return {"_id": "root-oid", "code": "root"}
        return None

    async def update_one(self, query, update, **kwargs):
        self.last_update = (query, update)
        return SimpleNamespace(upserted_id=None, modified_count=1)

    async def insert_one(self, doc):
        return SimpleNamespace(inserted_id="emp-oid")

    async def find_one_and_update(self, *args, **kwargs):
        return {"_id": "oid"}


class _FakeDB:
    def __init__(self) -> None:
        self._cols: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._cols.setdefault(name, _FakeCollection())


def _patch_provision_internals(monkeypatch):
    """Patch every heavy internal of provision_tenant with lightweight fakes."""
    captured: dict[str, object] = {}

    async def _noop(*args, **kwargs):
        return None

    async def _fake_find_account(username, main_id):
        return {"_id": "admin-oid"}

    async def _fake_ensure_tenant_record(**kwargs):
        captured["tenant_record"] = kwargs
        return {"_id": "t", "main_id": kwargs["main_id"]}

    async def _fake_configure_quota(**kwargs):
        captured["quota"] = kwargs

    async def _fake_create_model(model, main_id):
        captured.setdefault("models", []).append(model)
        return "model-id"

    async def _fake_configure_knowledge(**kwargs):
        captured["knowledge"] = kwargs

    async def _fake_save_search(search, main_id):
        captured["search"] = search

    class _FakePositionRoles:
        def __init__(self, db) -> None:
            pass

        async def ensure_indexes(self):
            return None

        async def ensure_full_access_role(self, main_id):
            return {"_id": "role-id"}

        async def assign_role(self, *args, **kwargs):
            captured["assign"] = {"args": args, "kwargs": kwargs}

        async def complete_migration(self, *args, **kwargs):
            return None

    monkeypatch.setattr(tenant_provisioning, "ensure_group_exists", _noop)
    monkeypatch.setattr(tenant_provisioning, "ensure_bootstrap_account", _noop)
    monkeypatch.setattr(tenant_provisioning, "ensure_root_department", _noop)
    monkeypatch.setattr(tenant_provisioning, "find_account_by_username", _fake_find_account)
    monkeypatch.setattr(tenant_provisioning, "PositionRoleRepository", _FakePositionRoles)
    monkeypatch.setattr(
        tenant_provisioning,
        "get_admin_product_extension",
        lambda: SimpleNamespace(edition="enterprise", organization_defaults={}),
    )
    monkeypatch.setattr(tenant_provisioning, "configure_setup_quotas", _fake_configure_quota)
    monkeypatch.setattr(tenant_provisioning, "create_setup_model", _fake_create_model)
    monkeypatch.setattr(tenant_provisioning, "configure_setup_knowledge_models", _fake_configure_knowledge)
    monkeypatch.setattr(tenant_provisioning, "save_setup_search", _fake_save_search)
    monkeypatch.setattr(tenant_provisioning, "ensure_tenant_record", _fake_ensure_tenant_record)
    fake_db = _FakeDB()
    monkeypatch.setattr(tenant_provisioning, "get_db", lambda: fake_db)
    return captured, fake_db


def test_provision_tenant_minimal_skips_optional_blocks(monkeypatch) -> None:
    captured, _ = _patch_provision_internals(monkeypatch)
    result = asyncio.run(
        tenant_provisioning.provision_tenant(
            org_name="Acme",
            admin_username="admin",
            admin_password="adminpass123",
            admin_display_name="系统管理员",
        )
    )
    assert result.main_id
    assert result.org_name == "Acme"
    assert result.model_instance_id is None
    assert result.additional_model_instance_ids == []
    # tenant registry written
    assert captured["tenant_record"]["main_id"] == result.main_id
    assert captured["tenant_record"]["created_by"] == "setup-wizard"
    # optional blocks skipped — no connectivity checks happened
    assert "quota" not in captured
    assert "models" not in captured
    assert "knowledge" not in captured
    assert "search" not in captured
    # admin is the org owner when no employee is supplied
    assert captured["assign"]["args"][1] == "admin-oid"


def test_provision_tenant_with_all_optional_blocks(monkeypatch) -> None:
    captured, _ = _patch_provision_internals(monkeypatch)
    asyncio.run(
        tenant_provisioning.provision_tenant(
            org_name="Acme",
            admin_username="admin",
            admin_password="adminpass123",
            admin_display_name="系统管理员",
            employee_username="emp",
            employee_password="emppass1234",
            employee_name="Emp",
            model={"providerId": "openai", "modelName": "gpt-4o", "capability": "chat"},
            additional_models=[],
            external_search={"provider": "tavily"},
            quota={"total_tokens": 1000, "default_user_tokens": 100, "period": "monthly", "timezone": "Asia/Shanghai"},
        )
    )
    assert "quota" in captured
    assert "models" in captured
    assert "knowledge" in captured
    assert "search" in captured
    # employee becomes the org owner
    assert captured["assign"]["args"][1] == "emp-oid"


def test_provision_tenant_community_total_points_from_quota(monkeypatch) -> None:
    captured, fake_db = _patch_provision_internals(monkeypatch)
    monkeypatch.setattr(
        tenant_provisioning,
        "get_admin_product_extension",
        lambda: SimpleNamespace(edition="community", organization_defaults={}),
    )
    asyncio.run(
        tenant_provisioning.provision_tenant(
            org_name="Acme",
            admin_username="admin",
            admin_password="adminpass123",
            admin_display_name="系统管理员",
            quota={"total_tokens": 5000, "default_user_tokens": 200, "period": "monthly", "timezone": "Asia/Shanghai"},
        )
    )
    org_update = fake_db["organizations"].last_update
    assert org_update[1]["$set"]["total_points"] == 5000


def test_provision_tenant_rolls_back_on_failure(monkeypatch) -> None:
    """provision_tenant owns cleanup: any exception after main_id is allocated
    must trigger cleanup_failed_setup(main_id) and propagate."""
    captured: dict[str, object] = {}

    async def fake_next_main_id(org_name: str) -> str:
        return "fixed-main-id"

    async def boom(*args, **kwargs) -> None:
        raise RuntimeError("boom during ensure_group_exists")

    async def fake_cleanup(main_id: str) -> None:
        captured["main_id"] = main_id

    monkeypatch.setattr(tenant_provisioning, "_next_main_id", fake_next_main_id)
    monkeypatch.setattr(tenant_provisioning, "ensure_group_exists", boom)
    monkeypatch.setattr(tenant_provisioning, "cleanup_failed_setup", fake_cleanup)

    with pytest.raises(RuntimeError):
        asyncio.run(
            tenant_provisioning.provision_tenant(
                org_name="Acme Corp",
                admin_username="admin",
                admin_password="adminpass123",
                admin_display_name="系统管理员",
                employee_username="employee",
                employee_password="emppass1234",
                employee_name="Employee One",
                quota={"total_tokens": 100000, "default_user_tokens": 1000, "period": "monthly", "timezone": "Asia/Shanghai"},
                model=_model().model_dump(),
            )
        )
    assert captured["main_id"] == "fixed-main-id"
