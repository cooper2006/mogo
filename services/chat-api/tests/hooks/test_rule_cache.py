"""Tests for the 009 rule-source cache in ``turn_admission``.

Two invariants, both regressions found in the 2026-10-06 QA audit:

1. **Bounded** — the cache is keyed by tenant with no eviction, so every tenant
   that ever invoked a tool leaked an entry for the process lifetime, despite
   the docstring claiming it was "bounded to the tenants seen recently".
2. **Invalidated on write** — spec 009 FR-4 requires "规则变更即时生效（下一工具
   调用即按新规则求值）". A bare 2s TTL cannot honour that: a rule change was
   invisible for up to two seconds.
"""

from __future__ import annotations

import pytest

from app.dsh_runtime import turn_admission
from app.dsh_runtime.hooks.store import HookRuleStore


@pytest.fixture(autouse=True)
def _clear_cache():
    turn_admission.invalidate_rule_source_cache()
    yield
    turn_admission.invalidate_rule_source_cache()


def test_cache_is_bounded() -> None:
    """Exceeding the cap must evict, not grow without limit."""
    cap = turn_admission._RULE_SOURCE_CACHE_MAX
    assert cap > 0
    for i in range(cap + 50):
        turn_admission._cache_rule_source(f"t{i}", [{"rule_id": f"r{i}"}])
    assert len(turn_admission._RULE_SOURCE_CACHE) <= cap


def test_cache_evicts_so_recent_tenants_survive() -> None:
    """The entry just written must still be cached after eviction pressure."""
    cap = turn_admission._RULE_SOURCE_CACHE_MAX
    for i in range(cap + 10):
        turn_admission._cache_rule_source(f"old-{i}", [{"n": i}])
    turn_admission._cache_rule_source("fresh", [{"n": "fresh"}])
    assert "fresh" in turn_admission._RULE_SOURCE_CACHE


def test_invalidate_single_tenant() -> None:
    turn_admission._cache_rule_source("t1", [])
    turn_admission._cache_rule_source("t2", [])
    turn_admission.invalidate_rule_source_cache("t1")
    assert "t1" not in turn_admission._RULE_SOURCE_CACHE
    assert "t2" in turn_admission._RULE_SOURCE_CACHE


def test_invalidate_all_tenants() -> None:
    turn_admission._cache_rule_source("t1", [])
    turn_admission._cache_rule_source("t2", [])
    turn_admission.invalidate_rule_source_cache()
    assert turn_admission._RULE_SOURCE_CACHE == {}


@pytest.mark.asyncio
async def test_rule_mutation_invalidates_cache_fr4() -> None:
    """FR-4: a rule change must be visible to the next tool call.

    Regression guard — with TTL-only caching, `create`/`update`/`delete` left the
    stale rule set in place for up to ``_RULE_SOURCE_CACHE_TTL`` seconds.
    """
    store = HookRuleStore()
    turn_admission._cache_rule_source("t1", [{"rule_id": "stale"}])

    await store.create(
        scope="tool", rule_type="observe", rule_config={"n": 1}, tenant_id="t1"
    )

    # The cached (stale) entry must have been dropped by the mutation.
    assert "t1" not in turn_admission._RULE_SOURCE_CACHE


@pytest.mark.asyncio
async def test_update_invalidates_cache() -> None:
    store = HookRuleStore()
    doc = await store.create(
        scope="tool", rule_type="observe", rule_config={"n": 1}, tenant_id="t1"
    )
    turn_admission._cache_rule_source("t1", [{"rule_id": doc.rule_id}])
    await store.update(doc.rule_id, enabled=False, tenant_id="t1")
    assert "t1" not in turn_admission._RULE_SOURCE_CACHE


@pytest.mark.asyncio
async def test_delete_invalidates_cache() -> None:
    store = HookRuleStore()
    doc = await store.create(
        scope="tool", rule_type="observe", rule_config={}, tenant_id="t1"
    )
    turn_admission._cache_rule_source("t1", [{"rule_id": doc.rule_id}])
    assert await store.delete(doc.rule_id, tenant_id="t1") is True
    assert "t1" not in turn_admission._RULE_SOURCE_CACHE


@pytest.mark.asyncio
async def test_cross_tenant_mutation_does_not_evict_other_tenant() -> None:
    """A t2 write must not wipe t1's cache entry."""
    store = HookRuleStore()
    turn_admission._cache_rule_source("t1", [{"n": 1}])
    turn_admission._cache_rule_source("t2", [{"n": 2}])

    await store.create(
        scope="tool", rule_type="observe", rule_config={}, tenant_id="t2"
    )

    assert "t2" not in turn_admission._RULE_SOURCE_CACHE
    assert "t1" in turn_admission._RULE_SOURCE_CACHE


@pytest.mark.asyncio
async def test_broken_invalidator_does_not_block_writes() -> None:
    """A cache callback that raises must not break rule persistence."""
    from app.dsh_runtime.hooks import store as store_mod

    def _boom(_tenant_id: str = "") -> None:
        raise RuntimeError("cache exploded")

    store_mod.register_rule_cache_invalidator(_boom)
    try:
        store = HookRuleStore()
        # Runs through _notify_rule_cache_changed; must not raise.
        created = await store.create(
            scope="tool", rule_type="observe", rule_config={}, tenant_id="tX"
        )
        assert created.tenant_id == "tX"
    finally:
        store_mod._RULE_CACHE_INVALIDATORS.remove(_boom)
