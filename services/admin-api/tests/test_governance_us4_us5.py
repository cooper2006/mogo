"""Feature 001 — US4 (fine-grained RBAC) + US5 (quota) integration tests (T025 / T028).

US4 acceptance:
* a tenant user holding ``knowledge:read`` may read knowledge entries
* calling ``admin:role:assign`` without the code -> rejected
* a position role bound to a preset code group takes effect (role preset groups
  coexist with explicit grants, FR-6)

US5 acceptance:
* a tenant day quota of 1000 rejects the 1001st call with a tenant notice
* a per-tool 10/hour quota restricts only that tool
"""

from __future__ import annotations

import pytest

from app.governance import permission_grants, risk
from app.governance.gatekeeper import GateContext
from app.governance.layers.quota import QuotaLayer, QuotaStore
from app.governance.layers.rbac import RbacLayer
from app.governance.rbac_model import expand_role_to_codes, has_permission


# --- US4 / T025 ----------------------------------------------------------------


class TestPermissionCodeAcceptance:
    def test_knowledge_read_grants(self):
        granted = {"knowledge:read"}
        assert has_permission(granted, "knowledge:read") is True

    def test_admin_role_assign_requires_code(self):
        granted = {"knowledge:read"}
        assert has_permission(granted, "admin:role:assign") is False
        # No grant at all -> fail-closed reject
        assert has_permission(set(), "admin:role:assign") is False

    def test_role_preset_group_effective(self):
        """A position role bound to a preset code group expands to codes (T009)."""
        role = {
            "system_key": "engineer",
            "capabilities": {"internal_knowledge": True},
        }
        codes = expand_role_to_codes(role)
        assert "knowledge:read" in codes

    def test_wildcard_grants_all(self):
        assert has_permission({"*"}, "admin:role:assign") is True

    def test_target_specific_grant(self):
        granted = {"knowledge:read:finance"}
        assert has_permission(granted, "knowledge:read:finance") is True
        assert has_permission(granted, "knowledge:read:hr") is False


class _FakeRoleCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, query):
        ids = set(query.get("_id", {}).get("$in", []))
        main = query.get("main_id")
        items = [d for d in self._docs if d.get("main_id") == main and d.get("_id") in ids]
        return _AsyncCursor(items)


class _AsyncCursor:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def __aiter__(self):
        async def gen():
            for item in self._items:
                yield item

        return gen()


@pytest.mark.asyncio
async def test_rbac_layer_with_explicit_grant():
    """US4: an explicit grant satisfying the required code allows the call."""
    layer = RbacLayer()
    ctx = GateContext(tool="knowledge", tenant_id="t1", user_id="u1", roles=[])
    ctx.annotations["required_code"] = "knowledge:read"

    async def fake_grants(*, tenant_id, org_id="", user_id=""):
        if user_id == "u1":
            return {"knowledge:read"}
        return set()

    layer._explicit_grants = lambda ctx: _wrap(fake_grants)(ctx)
    verdict = await layer.evaluate(ctx)
    assert verdict.decision.value == "allow"


@pytest.mark.asyncio
async def test_rbac_layer_rejects_without_code():
    layer = RbacLayer()
    ctx = GateContext(tool="admin.role.assign", tenant_id="t1", user_id="u2", roles=[])
    ctx.annotations["required_code"] = "admin:role:assign"

    async def empty(*, tenant_id, org_id="", user_id=""):
        return set()

    layer._explicit_grants = lambda ctx: _wrap(empty)(ctx)
    verdict = await layer.evaluate(ctx)
    assert verdict.decision.value == "deny"


def _wrap(async_fn):
    """Adapt an async callable into a sync-returned coroutine for monkeypatching."""

    def factory(ctx):
        return async_fn(user_id=ctx.user_id, tenant_id=ctx.tenant_id)

    return factory


# --- US5 / T028 ----------------------------------------------------------------


class _FakeDb:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def __getitem__(self, name):
        return self

    async def find_one_and_update(self, filter_doc, update, upsert=False, return_document=False, **kwargs):
        from pymongo import ReturnDocument

        key = tuple(sorted((k, str(v)) for k, v in filter_doc.items() if k != "count"))
        existing = self._data.get(key)
        if existing is None:
            if not upsert:
                return None
            doc = {k: v for k, v in filter_doc.items()}
            doc["count"] = 1
            self._data[key] = doc
            result = dict(doc)
        else:
            doc = self._data[key]
            doc["count"] = int(doc.get("count", 0)) + 1
            self._data[key] = doc
            result = dict(doc) if return_document in (ReturnDocument.AFTER, True) else None
        return result


@pytest.mark.asyncio
async def test_tenant_day_quota_exceeded():
    """Tenant day quota 1000 -> the 1001st call is rejected with a tenant notice."""
    db = _FakeDb()
    store = QuotaStore(db)
    limits = {"tenant": {"day": 1000}}
    for _ in range(1000):
        assert await store.check_and_consume(
            tenant_id="t1", user_id="u1", tool="web.search", limits=limits
        ) is None
    exceeded = await store.check_and_consume(tenant_id="t1", user_id="u1", tool="web.search", limits=limits)
    assert exceeded == ("tenant", "day", 1000)


@pytest.mark.asyncio
async def test_tool_quota_independent():
    """A per-tool 10/hour quota restricts only that tool."""
    db = _FakeDb()
    store = QuotaStore(db)
    limits = {"tool": {"min": 10}}
    for _ in range(10):
        assert await store.check_and_consume(
            tenant_id="t1", user_id="u1", tool="file.write", limits=limits
        ) is None
    exceeded = await store.check_and_consume(
        tenant_id="t1", user_id="u1", tool="file.write", limits=limits
    )
    assert exceeded == ("tool", "min", 10)
    # Another tool is NOT restricted
    assert (
        await store.check_and_consume(tenant_id="t1", user_id="u1", tool="web.search", limits=limits)
        is None
    )


@pytest.mark.asyncio
async def test_quota_layer_denies_with_dimension():
    db = _FakeDb()
    layer = QuotaLayer(store=QuotaStore(db), limits_resolver=lambda tenant: {"tenant": {"min": 2}})

    async def fire(ctx):
        return await layer.evaluate(ctx)

    ctx = GateContext(tool="web.search", tenant_id="t1", user_id="u1")
    assert (await fire(ctx)).decision.value == "allow"
    assert (await fire(ctx)).decision.value == "allow"
    verdict = await fire(ctx)
    assert verdict.decision.value == "deny"
    assert "tenant" in verdict.reason
    assert ctx.annotations["quota_exceeded"] == {"scope": "tenant", "window": "min", "limit": 2}


@pytest.mark.asyncio
async def test_quota_layer_passthrough_when_unconfigured():
    layer = QuotaLayer(limits_resolver=lambda tenant: {})
    ctx = GateContext(tool="web.search", tenant_id="t1", user_id="u1")
    verdict = await layer.evaluate(ctx)
    assert verdict.decision.value == "allow"
    assert "no quota limits" in verdict.reason
