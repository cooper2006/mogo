"""Contract tests for feature 033-canary-rollout (ratio ladder + shadow).

Covers SC-001~SC-005:
* T017 阶梯推进（样本不足停档 / 达标推进 / 100% 置 PROMOTED / 历史可查 / 手动推进）
* T018 影子隔离（记录落 `skill_shadow_runs`、影子失败不触发回滚、不影响用户结果）
* T019 分流确定性与比例近似 + tenants/ratio 叠加
* T020 016 回滚回归（自动 + 手动）在比例维度下的 ratio 归零与 stable_version 保持
* T021 存量 `skill_rollouts` 行（无新字段）读取默认 ratio=1.0 / shadow=False
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.skill_market.canary import (
    DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    DEFAULT_MIN_CANARY_SAMPLES,
    DEFAULT_TRAFFIC_LADDER,
    SHADOW_RUNS_COLLECTION,
    CanaryError,
    LadderStep,
    Rollout,
    RolloutState,
    advance_ladder,
    apply_rollback,
    evaluate_canary,
    fetch_shadow_stats,
    record_shadow_run,
    resolve_assignment,
    scan_and_advance_ladder,
    scan_and_auto_rollback,
    should_shadow,
    _rollout_to_row,
    _row_to_rollout,
    default_ladder,
)


def _rollout(**overrides):
    base = dict(skill_id="sk", version=3, stable_version=2)
    base.update(overrides)
    return Rollout(**base)


# --- 分流：确定性 + 比例近似 + tenants/ratio 叠加（T019 / SC-001） ----------

def test_resolve_assignment_is_deterministic_for_same_user() -> None:
    """同一用户在整个灰度期内分配结果一致（FR-003 粘滞）。"""
    rollout = _rollout(traffic_ratio=0.10)
    users = [f"user-{i}" for i in range(200)]
    for user in users:
        first = resolve_assignment(rollout, tenant_id="t1", user_id=user)
        for _ in range(5):
            assert resolve_assignment(rollout, tenant_id="t1", user_id=user) == first


def test_resolve_assignment_ratio_approximation_within_tolerance() -> None:
    """大样本下分流比例接近配置 ratio（统计容差内）。"""
    rollout = _rollout(traffic_ratio=0.50)
    total = 20000
    users = [f"u{i}" for i in range(total)]
    hits = sum(
        1 for user in users if resolve_assignment(rollout, tenant_id="tenant", user_id=user)
    )
    assert hits / total == pytest.approx(0.50, abs=0.02)


def test_target_tenants_and_ratio_stack() -> None:
    """tenants 与 ratio 叠加：非目标租户一律稳定版（FR-002 决策表 #2）。"""
    rollout = _rollout(target_tenants=["allowed"], traffic_ratio=1.0)
    assert resolve_assignment(rollout, tenant_id="other", user_id="u1") is False
    # 租户子集内仍按 ratio 分流；空 tenants = 全量 100%。
    whole = _rollout(traffic_ratio=1.0)
    assert resolve_assignment(whole, tenant_id="any", user_id="u1") is True


def test_resolve_assignment_rejects_invalid_ratio() -> None:
    """ratio=0 或 >1 → 拒绝（edge case：traffic_ratio 非法值）。"""
    rollout = _rollout(traffic_ratio=0.0)
    with pytest.raises(CanaryError):
        resolve_assignment(rollout, tenant_id="t", user_id="u")
    # ratio > 1 连构造都拒绝（模型层兜底）。
    with pytest.raises(CanaryError):
        _rollout(traffic_ratio=1.5)


# --- 阶梯推进（T017 / SC-002） ----------------------------------------------

def test_advance_ladder_holds_when_samples_insufficient() -> None:
    """当前档样本 < min_samples → 停在当前档（US1 场景 3）。"""
    rollout = _rollout(traffic_ratio=0.01)
    rollout.record_calls(calls=10, errors=0)
    decision = advance_ladder(rollout)
    assert decision.advanced is False
    assert decision.promoted is False
    assert rollout.current_step == 0
    assert rollout.traffic_ratio == 0.01


def test_advance_ladder_holds_when_error_rate_breached() -> None:
    """异常率超阈值 → 不推进（回滚交给扫描器判定）。"""
    rollout = _rollout(traffic_ratio=0.01)
    rollout.record_calls(calls=100, errors=30)
    decision = advance_ladder(rollout, threshold=0.20)
    assert decision.advanced is False
    assert rollout.current_step == 0


def test_advance_ladder_walks_through_default_steps_and_promotes() -> None:
    """达标推进 1%→10%→50%→100%，末档稳定后置 PROMOTED（US1 场景 2/4）。"""
    steps: list[float] = []
    promoted = False
    rollout = _rollout(traffic_ratio=0.01)
    for _ in range(4):
        rollout.record_calls(calls=100, errors=0)
        decision = advance_ladder(rollout)
        if decision.promoted:
            promoted = True
        elif decision.advanced:
            steps.append(rollout.traffic_ratio)
    assert steps == [0.10, 0.50, 1.00]
    assert promoted is True
    assert rollout.state == RolloutState.PROMOTED.value
    assert rollout.current_step == 3
    assert rollout.current_ratio == 1.0
    # 推进历史逐档落库，可查（FR-005）。
    assert len(rollout.ladder_history) == 4
    assert {round(item["ratio"], 2) for item in rollout.ladder_history} == {0.01, 0.10, 0.50, 1.00}
    # PROMOTED 后再评估不再推进。
    again = advance_ladder(rollout)
    assert again.advanced is False and again.promoted is True


def test_advance_ladder_respects_per_rung_min_samples() -> None:
    """档位可覆盖 min_samples（LadderStep.min_samples）。"""
    ladder = [
        LadderStep(ratio=0.01, min_samples=50),
        LadderStep(ratio=1.00, min_samples=5),
    ]
    rollout = _rollout(traffic_ratio=0.01, ladder=ladder)
    rollout.record_calls(calls=30, errors=0)
    decision = advance_ladder(rollout, min_samples=DEFAULT_MIN_CANARY_SAMPLES)
    assert decision.advanced is False  # 30 < 50（档位覆盖）
    assert decision.min_samples_required == 50


def test_manual_advance_via_scanner_scan() -> None:
    """扫描器级自动推进（scan_and_advance_ladder）持久化档位与 traffic_ratio。"""
    class _Coll:
        def __init__(self):
            self.rows = [_rollout_to_row(_rollout(traffic_ratio=0.01))]
            self.replaced = []

        def find(self, query):
            class _Cur:
                async def to_list(self, length):
                    return self_rows[:length]
            self_rows = [r for r in self.rows if r.get("state") in query["state"]["$in"]]
            return _Cur()

        async def replace_one(self, query, doc):
            for row in self.rows:
                if row["skill_id"] == query["skill_id"]:
                    row.update(doc)
                    self.replaced.append(dict(doc))
                    return True
            return False

    class _DB:
        def __init__(self, coll):
            self._coll = coll

        def __getitem__(self, name):
            return self._coll

    coll = _Coll()
    coll.rows[0]["call_count"] = 100
    coll.rows[0]["error_count"] = 2
    results = asyncio.run(scan_and_advance_ladder(_DB(coll), min_samples=20, threshold=0.20))
    assert len(results) == 1
    assert results[0]["action"] == "ladder_advance"
    assert coll.rows[0]["traffic_ratio"] == 0.10
    assert coll.rows[0]["current_step"] == 1
    assert coll.rows[0]["state"] == RolloutState.RUNNING.value


# --- 影子隔离（T018 / SC-003） ----------------------------------------------

def test_should_shadow_only_for_missed_users() -> None:
    """命中 ratio 的用户不再影子双跑；未命中且开启影子才双跑（US2 场景 4）。"""
    rollout = _rollout(traffic_ratio=1.0, shadow_enabled=True)
    assert should_shadow(rollout, tenant_id="t", user_id="u1") is False  # 全量命中
    partial = _rollout(traffic_ratio=0.5, shadow_enabled=True)
    users = [f"u{i}" for i in range(1000)]
    hit = [u for u in users if not should_shadow(partial, tenant_id="t", user_id=u)]
    missed = [u for u in users if should_shadow(partial, tenant_id="t", user_id=u)]
    assert hit and missed
    assert len(missed) / len(users) == pytest.approx(0.5, abs=0.05)
    # 关闭影子 → 永不双跑。
    off = _rollout(traffic_ratio=0.5, shadow_enabled=False)
    assert not any(should_shadow(off, tenant_id="t", user_id=u) for u in users)


def test_record_shadow_run_writes_only_to_shadow_collection() -> None:
    """影子记录只落 `skill_shadow_runs`，不进入 rollout 计数（FR-008）。"""

    class _Coll:
        def __init__(self):
            self.docs = []

        async def insert_one(self, doc):
            self.docs.append(doc)
            return True

    class _DB:
        def __init__(self, coll):
            self._coll = coll

        def __getitem__(self, name):
            assert name == SHADOW_RUNS_COLLECTION
            return self._coll

    coll = _Coll()
    record = asyncio.run(
        record_shadow_run(
            _DB(coll),
            skill_id="sk", version=3, tenant_id="t1", user_id="u1",
            duration_ms=120, ok=False, error="boom",
        )
    )
    assert record["ok"] is False
    assert len(coll.docs) == 1
    assert coll.docs[0]["skill_id"] == "sk"


def test_shadow_failure_does_not_touch_rollback_counters() -> None:
    """影子失败绝不进入 call_count/error_count → 不触发回滚（FR-009）。"""
    rollout = _rollout(traffic_ratio=0.5, shadow_enabled=True)
    # 模拟多次影子失败后 rollout 计数仍为 0（影子路径完全隔离）。
    for _ in range(10):
        asyncio.run(
            record_shadow_run(
                _MemoryDB(), skill_id="sk", version=3, tenant_id="t", user_id="u",
                duration_ms=1, ok=False, error="boom",
            )
        )
    assert rollout.call_count == 0 and rollout.error_count == 0
    decision = evaluate_canary(rollout)
    assert decision.should_rollback is False


def test_shadow_stats_basic_aggregation() -> None:
    """影子统计返回调用数/成功率/耗时（FR-012，不做深度比对）。"""

    class _Coll:
        def __init__(self):
            self._docs = [
                {"duration_ms": 100, "ok": True},
                {"duration_ms": 200, "ok": True},
                {"duration_ms": 300, "ok": False},
            ]

        async def count_documents(self, query):
            if query.get("ok") is True:
                return 2
            return len(self._docs)

        def find(self, query):
            docs = self._docs

            class _Cur:
                async def to_list(self, length):
                    return docs[:length]
            return _Cur()

    class _DB:
        def __init__(self, coll):
            self._coll = coll

        def __getitem__(self, name):
            assert name == SHADOW_RUNS_COLLECTION
            return self._coll

    stats = asyncio.run(fetch_shadow_stats(_DB(_Coll()), skill_id="sk", version=3))
    assert stats["total"] == 3
    assert stats["ok"] == 2
    assert stats["success_rate"] == pytest.approx(2 / 3, abs=0.01)
    assert stats["avg_duration_ms"] == pytest.approx(200.0)


class _MemoryDB:
    """Minimal DB shim used only to receive shadow-run inserts."""

    def __init__(self):
        self.coll = _MemColl()

    def __getitem__(self, name):
        assert name == SHADOW_RUNS_COLLECTION
        return self.coll


class _MemColl:
    async def insert_one(self, doc):
        return True


# --- 016 回滚回归 + 比例维度（T020 / SC-004） -------------------------------

def test_rollback_zeroes_ratio_and_keeps_stable_version() -> None:
    """比例灰度回滚后 ratio 归零、状态 rolled_back、stable_version 指向上版。"""
    rollout = _rollout(traffic_ratio=0.5, stable_version=2)
    rollout.record_calls(calls=100, errors=50)  # 50% > 20%
    decision = evaluate_canary(rollout, threshold=0.20, min_samples=20)
    assert decision.should_rollback is True
    record = apply_rollback(rollout, decision)
    assert record["toVersion"] == 2
    assert record["fromVersion"] == 3
    assert rollout.state == RolloutState.ROLLED_BACK.value
    assert rollout.traffic_ratio == 0.0


def test_auto_rollback_scan_zeroes_ratio() -> None:
    """自动回滚扫描器在比例维度下同样把 ratio 归零（US3 场景 1）。"""

    class _Coll:
        def __init__(self):
            self.rows = [_rollout_to_row(_rollout(traffic_ratio=0.5))]
            self.rows[0]["call_count"] = 100
            self.rows[0]["error_count"] = 50

        def find(self, query):
            rows = [r for r in self.rows if r["state"] in query["state"]["$in"]]

            class _Cur:
                async def to_list(self, length):
                    return rows[:length]
            return _Cur()

        async def replace_one(self, query, doc):
            for row in self.rows:
                if row["skill_id"] == query["skill_id"]:
                    row.update(doc)
                    return True
            return False

    class _DB:
        def __init__(self, coll):
            self._coll = coll

        def __getitem__(self, name):
            return self._coll

    coll = _Coll()
    applied = asyncio.run(scan_and_auto_rollback(_DB(coll)))
    assert [item["skillId"] for item in applied] == ["sk"]
    assert coll.rows[0]["state"] == "rolled_back"
    assert coll.rows[0]["traffic_ratio"] == 0.0


def test_016_rollback_semantics_preserved() -> None:
    """小样本保护保留：样本 <20 即使错误率高也不回滚（US3 场景 3）。"""
    rollout = _rollout(traffic_ratio=0.5)
    rollout.record_calls(calls=10, errors=9)
    decision = evaluate_canary(rollout, threshold=0.20, min_samples=20)
    assert decision.should_rollback is False
    assert decision.sample_sufficient is False


# --- 存量行兼容（T021 / SC-005） -------------------------------------------

def test_legacy_row_without_new_fields_defaults_to_full_traffic() -> None:
    """无 traffic_ratio/ladder/shadow 的旧行读取默认 ratio=1.0、shadow=False。"""
    legacy_row = {
        "skill_id": "legacy",
        "version": 2,
        "stable_version": 1,
        "target_tenants": ["t1"],
        "state": "running",
        "error_count": 1,
        "call_count": 100,
    }
    rollout = _row_to_rollout(legacy_row)
    assert rollout.traffic_ratio == 1.0
    assert rollout.shadow_enabled is False
    assert [step.ratio for step in rollout.ladder] == list(DEFAULT_TRAFFIC_LADDER)
    # 既有按租户灰度行为不回退：target_tenants 命中即全量命中。
    assert resolve_assignment(rollout, tenant_id="t1", user_id="u1") is True


def test_ladder_history_survives_row_roundtrip() -> None:
    """阶梯与历史经 _row_to_rollout/_rollout_to_row 往返无损。"""
    rollout = _rollout(traffic_ratio=0.10, shadow_enabled=True)
    rollout.record_calls(calls=100, errors=1)
    decision = advance_ladder(rollout)
    assert decision.advanced
    restored = _row_to_rollout(_rollout_to_row(rollout))
    assert restored.traffic_ratio == rollout.traffic_ratio
    assert restored.current_step == rollout.current_step
    assert restored.shadow_enabled is True
    assert restored.ladder_history == rollout.ladder_history
    assert [step.ratio for step in restored.ladder] == list(DEFAULT_TRAFFIC_LADDER)


def test_default_ladder_matches_spec() -> None:
    """默认阶梯 = 1%→10%→50%→100%（决策表 #4）。"""
    assert default_ladder() == [LadderStep(r) for r in DEFAULT_TRAFFIC_LADDER]
    assert list(DEFAULT_TRAFFIC_LADDER) == [0.01, 0.10, 0.50, 1.00]