import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints import dsh_plugins as endpoint
from app.api.principal import ApiPrincipal


class _Collection:
    def __init__(self, row):
        self.row = row

    async def find_one(self, *_args):
        return self.row


class _Database:
    def __init__(self, row):
        self.dsh_plugin_installations = _Collection(row)


def test_personal_install_rejects_name_of_restricted_enterprise_plugin(monkeypatch):
    monkeypatch.setattr(endpoint, "get_db", lambda: _Database({"_id": "org-plugin"}))

    async def deny(*_args, **_kwargs):
        return set()

    monkeypatch.setattr(endpoint, "filter_allowed_resource_ids", deny)
    principal = ApiPrincipal(kind="end_user", tenant_id="tenant", user_id="employee")
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint._check_personal_name(principal, "employee", "restricted"))
    assert error.value.status_code == 403


def test_failed_initial_audience_removes_new_plugin(monkeypatch):
    monkeypatch.setattr(endpoint, "get_db", lambda: _Database(None))
    removed = []

    async def save(**_kwargs):
        return {"id": "new-id", "name": "new"}

    async def remove(**kwargs):
        removed.append(kwargs)
        return True

    async def fail(*_args):
        raise RuntimeError("policy store unavailable")

    monkeypatch.setattr(endpoint.repository, "save", save)
    monkeypatch.setattr(endpoint.repository, "remove", remove)
    monkeypatch.setattr(endpoint, "_initialize_organization_access", fail)
    principal = ApiPrincipal(kind="admin_service", tenant_id="tenant")
    with pytest.raises(RuntimeError, match="policy store unavailable"):
        asyncio.run(endpoint._save_inspected_plugin(principal, "", {"name": "new"}))
    assert removed == [{"tenant_id": "tenant", "user_id": "", "plugin_id": "new-id"}]
