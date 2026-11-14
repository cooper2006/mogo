"""FR-2 / FR-3 / FR-4 (QF-525/526/527) MFA 强制策略测试.

覆盖：高权限账号必须绑定 MFA、第二因子限流（5 次 / 300s）、TOTP 防重放
（±1 步窗口）、内存 store、Mongo store 的 fake 集成。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.security import mfa_policy as mp
from app.security.audit_events import InMemoryAuditDb


ADMIN = mp.AccountMfaState(
    user_id="u-1",
    username="admin",
    tenant_id="t-1",
    role=mp.TENANT_ADMIN_ROLE,
    mfa_enabled=True,
    has_mfa_secret=True,
)

MEMBER = mp.AccountMfaState(user_id="u-2", username="alice", tenant_id="t-1", role="member")


# ---------------------------------------------------------------------------
# 高权限判定（FR-2）
# ---------------------------------------------------------------------------


def test_high_privilege_roles_are_detected():
    assert mp.is_high_privilege_role(mp.PLATFORM_ADMIN_ROLE)
    assert mp.is_high_privilege_role(mp.TENANT_ADMIN_ROLE)
    assert mp.is_high_privilege_role("  tenant_admin ")
    assert mp.is_high_privilege_role("PLATFORM_ADMIN")


def test_member_role_is_not_high_privilege():
    assert not mp.is_high_privilege_role("member")
    assert not mp.is_high_privilege_role("viewer")
    assert not mp.is_high_privilege_role("")
    assert not mp.is_high_privilege_role(None)
    assert not mp.is_high_privilege_role(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 登录闸门判定（FR-2 + FR-3）
# ---------------------------------------------------------------------------


def test_member_can_enter_without_mfa():
    decision = mp.decide_login_gate(MEMBER)
    assert decision.action == mp.DECISION_NOT_REQUIRED
    assert decision.blocks_business_access is False


def test_unbound_admin_must_bind_before_entering():
    unbound = mp.AccountMfaState(user_id="u-3", username="boss", role=mp.PLATFORM_ADMIN_ROLE)
    decision = mp.decide_login_gate(unbound)
    assert decision.action == mp.DECISION_BIND_REQUIRED
    assert decision.blocks_business_access is True
    assert decision.reason_code == "mfa_not_bound"


def test_enabled_admin_must_verify_second_factor():
    decision = mp.decide_login_gate(ADMIN)
    assert decision.action == mp.DECISION_VERIFY_REQUIRED
    assert decision.blocks_business_access is True
    assert decision.reason_code == "mfa_enabled"


def test_admin_with_mfa_flag_but_no_secret_is_treated_as_unbound():
    state = mp.AccountMfaState(user_id="u-4", username="x", role="tenant_admin", mfa_enabled=True)
    decision = mp.decide_login_gate(state)
    assert decision.action == mp.DECISION_BIND_REQUIRED


def test_max_failures_locks_the_account():
    decision = mp.decide_login_gate(ADMIN, failures=mp.MAX_FAILURES)
    assert decision.action == mp.DECISION_LOCKED
    assert decision.reason_code == "rate_limited"
    assert decision.attempts_remaining == 0
    assert decision.locked_until is not None


def test_lockout_beats_verify_order():
    # 即使已绑定 MFA，达到失败上限后仍然锁定
    decision = mp.decide_login_gate(ADMIN, failures=mp.MAX_FAILURES, now=1000.0)
    assert decision.action == mp.DECISION_LOCKED
    assert decision.locked_until == datetime.fromtimestamp(1000.0 + mp.LOCKOUT_WINDOW_SECONDS, tz=timezone.utc)


def test_attempts_remaining_countdown():
    decision = mp.decide_login_gate(ADMIN, failures=3)
    assert decision.attempts_remaining == mp.MAX_FAILURES - 3


def test_decide_login_gate_accepts_injected_clock():
    d1 = mp.decide_login_gate(ADMIN, now=1000.0)
    d2 = mp.decide_login_gate(ADMIN, now=1000.0)
    assert d1.action == d2.action == mp.DECISION_VERIFY_REQUIRED


def test_account_state_from_row_defaults_safely():
    state = mp.AccountMfaState.from_row({"_id": "abc", "username": "bob"})
    assert state.user_id == "abc"
    assert state.username == "bob"
    assert state.mfa_enabled is False
    assert state.has_mfa_secret is False
    assert mp.decide_login_gate(state).action == mp.DECISION_NOT_REQUIRED


def test_account_state_from_row_picks_up_mfa_secret():
    state = mp.AccountMfaState.from_row(
        {"id": "u-9", "username": "boss", "role": "platform_admin", "mfa_enabled": True, "mfa_secret": "totp://x"}
    )
    assert state.has_mfa_secret is True
    assert mp.decide_login_gate(state).action == mp.DECISION_VERIFY_REQUIRED


# ---------------------------------------------------------------------------
# 限流（FR-3）
# ---------------------------------------------------------------------------


def test_failure_key_is_scoped_to_username_tenant_ip():
    a = mp.failure_key(username="Alice", tenant_id="t-1", client_ip="10.0.0.1")
    b = mp.failure_key(username="alice", tenant_id="t-1", client_ip="10.0.0.1")
    c = mp.failure_key(username="alice", tenant_id="t-2", client_ip="10.0.0.1")
    d = mp.failure_key(username="alice", tenant_id="t-1", client_ip="10.0.0.2")
    assert a == b  # username 大小写归一
    assert a != c  # 租户隔离
    assert a != d  # IP 隔离


def test_failure_key_handles_missing_values():
    key = mp.failure_key(username="", tenant_id="", client_ip="")
    assert key == "-|-|-"


def test_lockout_until_locked_threshold():
    assert mp.lockout_until_locked(mp.MAX_FAILURES - 1, 1000.0) is None
    assert mp.lockout_until_locked(mp.MAX_FAILURES, 1000.0) == 1000.0 + mp.LOCKOUT_WINDOW_SECONDS


def test_record_failure_counts_within_window():
    state = mp.reset_failures()
    s = mp.record_failure(state, 1000.0)
    assert s.failures == 1
    s = mp.record_failure(s, 1001.0)
    assert s.failures == 2
    assert s.locked_until is None


def test_record_failure_locks_after_max_failures():
    state = mp.reset_failures()
    current = state
    for i in range(mp.MAX_FAILURES):
        current = mp.record_failure(current, 1000.0 + i)
    assert current.failures == mp.MAX_FAILURES
    assert current.is_locked
    assert current.locked_until == 1000.0 + (mp.MAX_FAILURES - 1) + mp.LOCKOUT_WINDOW_SECONDS


def test_record_failure_ignores_failures_while_locked():
    state = mp.reset_failures()
    current = state
    for i in range(mp.MAX_FAILURES):
        current = mp.record_failure(current, 1000.0 + i)
    assert current.is_locked
    # 锁定期内继续失败不应延长锁定
    still_locked = mp.record_failure(current, 1000.0 + 50)
    assert still_locked == current


def test_effective_failures_resets_after_window():
    state = mp.LockoutState(failures=4, window_start=1000.0, locked_until=None)
    assert mp.effective_failures(state, 1000.0 + mp.LOCKOUT_WINDOW_SECONDS - 1) == 4
    assert mp.effective_failures(state, 1000.0 + mp.LOCKOUT_WINDOW_SECONDS + 1) == 0


def test_record_failure_resets_count_after_window():
    state = mp.LockoutState(failures=4, window_start=1000.0, locked_until=None)
    new_state = mp.record_failure(state, 1000.0 + mp.LOCKOUT_WINDOW_SECONDS + 5)
    assert new_state.failures == 1
    assert new_state.window_start == 1000.0 + mp.LOCKOUT_WINDOW_SECONDS + 5


def test_constants_match_spec():
    assert mp.MAX_FAILURES == 5
    assert mp.LOCKOUT_WINDOW_SECONDS == 300
    assert mp.TOTP_STEP_SECONDS == 30
    assert mp.TOTP_WINDOW == 1
    assert mp.TOTP_USED_STEP_TTL_SECONDS == 90


# ---------------------------------------------------------------------------
# TOTP 防重放（FR-4）
# ---------------------------------------------------------------------------


def test_candidate_steps_are_symmetric():
    assert mp.candidate_steps(10) == (9, 10, 11)
    assert mp.candidate_steps(10, window=0) == (10,)
    assert mp.candidate_steps(10, window=2) == (8, 9, 10, 11, 12)


def test_is_replay_detects_used_steps():
    assert mp.is_replay(mp.candidate_steps(10), {9, 10, 11})
    assert mp.is_replay([10], {9, 11}) is False
    assert mp.is_replay([10], {9, 10, 11}) is True
    assert not mp.is_replay(mp.candidate_steps(10), {5, 6, 7})
    assert not mp.is_replay([], {9, 10, 11})


def test_used_step_replay_across_window_steps():
    # 窗口内的任一步被使用，后续同窗口内重复即判重放
    used = {9, 10, 11}
    assert mp.is_replay([11], used)
    # 窗口外的 step 不判重放
    assert not mp.is_replay([12], used)
    assert not mp.is_replay([8], used)


@pytest.mark.asyncio
async def test_in_memory_used_step_store_roundtrip():
    store = mp.InMemoryUsedStepStore()
    expires = datetime.now(timezone.utc) + timedelta(seconds=mp.TOTP_USED_STEP_TTL_SECONDS)
    await store.mark_used("scope-1", mp.candidate_steps(10), expires_at=expires)
    used = await store.used_steps_for("scope-1")
    assert used == {9, 10, 11}
    assert mp.is_replay(mp.candidate_steps(10), used)


@pytest.mark.asyncio
async def test_in_memory_used_step_store_expires_entries():
    store = mp.InMemoryUsedStepStore()
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await store.mark_used("scope-1", [10], expires_at=past)
    assert await store.used_steps_for("scope-1") == set()


@pytest.mark.asyncio
async def test_in_memory_used_step_store_scopes_are_independent():
    store = mp.InMemoryUsedStepStore()
    expires = datetime.now(timezone.utc) + timedelta(seconds=90)
    await store.mark_used("scope-a", [10], expires_at=expires)
    await store.mark_used("scope-b", [20], expires_at=expires)
    assert await store.used_steps_for("scope-a") == {10}
    assert await store.used_steps_for("scope-b") == {20}


@pytest.mark.asyncio
async def test_in_memory_failure_tracker_records_and_locks():
    tracker = mp.InMemoryFailureTracker()
    key = mp.failure_key(username="admin", tenant_id="t-1", client_ip="1.2.3.4")
    now = 1000.0
    for i in range(mp.MAX_FAILURES - 1):
        state = await tracker.record_failure(key, now=now + i)
    assert not state.is_locked
    state = await tracker.record_failure(key, now=now + mp.MAX_FAILURES)
    assert state.is_locked
    # 锁定期内查询返回锁定状态
    locked = await tracker.get(key, now=now + mp.MAX_FAILURES + 1)
    assert locked.is_locked


@pytest.mark.asyncio
async def test_in_memory_failure_tracker_resets_after_window():
    tracker = mp.InMemoryFailureTracker()
    key = mp.failure_key(username="a", tenant_id="t", client_ip="i")
    await tracker.record_failure(key, now=1000.0)
    await tracker.record_failure(key, now=1001.0)
    # 窗口结束后计数归零
    state = await tracker.get(key, now=1000.0 + mp.LOCKOUT_WINDOW_SECONDS + 10)
    assert state.failures == 0
    assert not state.is_locked


@pytest.mark.asyncio
async def test_in_memory_failure_tracker_reset():
    tracker = mp.InMemoryFailureTracker()
    key = "k"
    await tracker.record_failure(key, now=1000.0)
    await tracker.reset(key)
    assert (await tracker.get(key, now=1000.0)).failures == 0


@pytest.mark.asyncio
async def test_in_memory_failure_tracker_snapshot():
    tracker = mp.InMemoryFailureTracker()
    await tracker.record_failure("k1", now=1.0)
    await tracker.record_failure("k2", now=1.0)
    assert set(tracker.snapshot()) == {"k1", "k2"}


def test_scope_for_combines_identity_and_secret():
    a = mp.MongoTotpUsedStepStore.scope_for(user_id="u-1", tenant_id="t-1", secret_hint="h1")
    b = mp.MongoTotpUsedStepStore.scope_for(user_id="u-1", tenant_id="t-1", secret_hint="h1")
    c = mp.MongoTotpUsedStepStore.scope_for(user_id="u-2", tenant_id="t-1", secret_hint="h1")
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_mongo_lockout_tracker_roundtrip_with_fake_db():
    db = InMemoryAuditDb()
    tracker = mp.MongoMfaLockoutTracker(db, collection="mfa_lockouts")
    key = "t-1|admin|1.2.3.4"
    state = await tracker.get(key, now=1000.0)
    assert state.failures == 0
    state = await tracker.record_failure(key, now=1000.0)
    assert state.failures == 1
    state = await tracker.record_failure(key, now=1001.0)
    assert state.failures == 2
    # 持久化生效：新实例读到同一计数
    tracker2 = mp.MongoMfaLockoutTracker(db, collection="mfa_lockouts")
    assert (await tracker2.get(key, now=1002.0)).failures == 2
    await tracker.reset(key)
    assert (await tracker.get(key, now=1002.0)).failures == 0


@pytest.mark.asyncio
async def test_mongo_used_step_store_roundtrip_with_fake_db():
    db = InMemoryAuditDb()
    store = mp.MongoTotpUsedStepStore(db, collection="mfa_used_steps")
    expires = datetime.now(timezone.utc) + timedelta(seconds=mp.TOTP_USED_STEP_TTL_SECONDS)
    await store.mark_used("scope-x", mp.candidate_steps(5), expires_at=expires)
    assert await store.used_steps_for("scope-x") == {4, 5, 6}
    assert await store.used_steps_for("scope-other") == set()


@pytest.mark.asyncio
async def test_mongo_used_step_store_expires_entries():
    db = InMemoryAuditDb()
    store = mp.MongoTotpUsedStepStore(db, collection="mfa_used_steps")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await store.mark_used("scope-x", [5], expires_at=past)
    assert await store.used_steps_for("scope-x") == set()


@pytest.mark.asyncio
async def test_mongo_used_step_store_ensure_indexes():
    db = InMemoryAuditDb()
    store = mp.MongoTotpUsedStepStore(db)
    await store.ensure_indexes()  # 不抛异常即通过（fake 集合忽略索引）


def test_messages_are_stable():
    assert mp.BIND_REQUIRED_MESSAGE
    assert mp.LOCKED_MESSAGE
    assert "MFA" in mp.BIND_REQUIRED_MESSAGE or "MFA" in mp.LOCKED_MESSAGE
