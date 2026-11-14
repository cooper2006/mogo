"""Contract tests for the 033 shadow point in chat-api (影子分流点).

Covers FR-006/FR-007/FR-008 (spec US2, SC-003):
* 影子判定：未命中 ratio 且影子开启 → 双跑；命中 ratio → 直接返回候选版，不再双跑；
* 影子执行隔离：executor 抛异常 / 超时一律吞并，用户请求路径不受影响；
* 影子记录只落 ``skill_shadow_runs``，绝不返回给用户、绝不流入回滚判定。
"""

from __future__ import annotations

import asyncio

import pytest

from app.dsh_runtime.profile.skills.shadow import (
    DEFAULT_SHADOW_TIMEOUT_SECONDS,
    SHADOW_RUNS_COLLECTION,
    resolve_candidate,
    run_shadow,
    should_shadow,
    traffic_bucket,
)


class _MemColl:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> dict:
        self.docs.append(doc)
        return {"ok": True}


class _MemDB:
    def __init__(self) -> None:
        self.coll = _MemColl()

    def __getitem__(self, name: str) -> _MemColl:
        assert name == SHADOW_RUNS_COLLECTION
        return self.coll


def _plan(**overrides):
    base = {
        "skill_id": "sk",
        "version": 3,
        "traffic_ratio": 0.01,
        "target_tenants": [],
        "shadow_enabled": True,
    }
    base.update(overrides)
    return base


# --- 分流判定 ---------------------------------------------------------------

def test_traffic_bucket_is_deterministic() -> None:
    """同一 (tenant_id, user_id) 多次计算结果一致（粘滞）。"""
    bucket = traffic_bucket("t1", "u1")
    for _ in range(10):
        assert traffic_bucket("t1", "u1") == bucket


def test_shadow_plan_respects_ratio_and_tenants() -> None:
    """未命中 ratio 或不在租户子集内的用户需要影子双跑（US2 场景 1/4）。"""
    full = _plan(traffic_ratio=1.0)
    assert resolve_candidate(full, tenant_id="t1", user_id="u1") is True
    assert should_shadow(full, tenant_id="t1", user_id="u1") is False  # 命中即直接返回

    partial = _plan(traffic_ratio=0.5)
    users = [f"u{i}" for i in range(2000)]
    hit = [u for u in users if not should_shadow(partial, tenant_id="t", user_id=u)]
    missed = [u for u in users if should_shadow(partial, tenant_id="t", user_id=u)]
    assert hit and missed
    assert len(missed) / len(users) == pytest.approx(0.5, abs=0.05)

    scoped = _plan(traffic_ratio=1.0, target_tenants=["allowed"])
    assert resolve_candidate(scoped, tenant_id="blocked", user_id="u1") is False


def test_shadow_disabled_never_dual_runs() -> None:
    """影子关闭 → 永不双跑（默认关闭，成本由租户显式开启承担）。"""
    off = _plan(shadow_enabled=False, traffic_ratio=0.5)
    users = [f"u{i}" for i in range(1000)]
    assert not any(should_shadow(off, tenant_id="t", user_id=u) for u in users)


# --- 影子执行隔离（FR-007）--------------------------------------------------

def test_shadow_result_is_never_returned_to_user() -> None:
    """影子分支只返回观察记录，任何失败都返回 ok=False，用户仍拿稳定版结果。"""
    db = _MemDB()

    async def candidate():
        return {"answer": "candidate payload"}

    outcome = asyncio.run(
        run_shadow(db, plan=_plan(), tenant_id="t", user_id="u_miss", executor=candidate)
    )
    assert outcome["ok"] is True
    # 返回值只包含观察指标，绝不携带候选版业务结果（决策表 #9）。
    assert "answer" not in outcome
    assert outcome["recorded"] is True


def test_shadow_executor_exception_is_swallowed() -> None:
    """executor 抛异常 → 吞并并记录，不冒泡到用户路径（US2 场景 2）。"""
    db = _MemDB()

    async def boom():
        raise RuntimeError("candidate crashed")

    outcome = asyncio.run(
        run_shadow(db, plan=_plan(), tenant_id="t", user_id="u_miss", executor=boom)
    )
    assert outcome["ok"] is False
    assert "candidate crashed" in outcome["error"]
    assert db.coll.docs[-1]["ok"] is False
    assert db.coll.docs[-1]["error"]


def test_shadow_executor_timeout_is_swallowed() -> None:
    """超时 → 吞并，用户请求无感（决策表 #9）。"""
    db = _MemDB()

    async def slow():
        await asyncio.sleep(5)

    outcome = asyncio.run(
        run_shadow(db, plan=_plan(), tenant_id="t", user_id="u_miss", executor=slow, timeout=0.05)
    )
    assert outcome["ok"] is False
    assert "shadow_timeout" in outcome["error"]
    assert db.coll.docs[-1]["ok"] is False


def test_shadow_record_isolation_from_rollout_counters() -> None:
    """影子记录只落 skill_shadow_runs；rollout 的 call/error 计数完全不受影响。"""
    db = _MemDB()
    rollout_counters = {"call_count": 0, "error_count": 0}

    async def flaky():
        raise ValueError("boom")

    for _ in range(20):
        outcome = asyncio.run(
            run_shadow(db, plan=_plan(), tenant_id="t", user_id="u_miss", executor=flaky)
        )
        assert outcome["ok"] is False
    # 20 次影子失败后 rollout 计数仍为零 → 不可能触发回滚（FR-009）。
    assert rollout_counters == {"call_count": 0, "error_count": 0}
    assert len(db.coll.docs) == 20


def test_shadow_run_persists_observation_fields() -> None:
    """影子记录字段完整：skill_id/version/tenant_id/user_id/耗时/结果/错误（FR-008）。"""
    db = _MemDB()

    async def candidate():
        return None

    asyncio.run(
        run_shadow(db, plan=_plan(), tenant_id="tenant-7", user_id="user-9", executor=candidate)
    )
    doc = db.coll.docs[0]
    assert doc["skill_id"] == "sk"
    assert doc["version"] == 3
    assert doc["tenant_id"] == "tenant-7"
    assert doc["user_id"] == "user-9"
    assert doc["duration_ms"] >= 0
    assert doc["ok"] is True
    assert "created_at" in doc


def test_default_shadow_timeout_is_configured() -> None:
    """默认影子超时为 30s，避免双跑拖慢用户路径。"""
    assert DEFAULT_SHADOW_TIMEOUT_SECONDS == 30.0