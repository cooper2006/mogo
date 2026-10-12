"""T013 集成测试：FR-2/FR-3/FR-4/FR-23 登录闸门组合层。

覆盖 :mod:`app.security.mfa_gate`（把 Phase 0 的纯逻辑与 Mongo 存储、
审计落点组合起来的一层）。全部使用内存 fake，不启动 MongoDB、不起真实
事件循环之外的网络，因此可以在 CI 里稳定重复。

覆盖点（对应 022 任务）：
- T011：登录闸门（高权限账号未绑 MFA → 阻断；5 次/300s → 锁定）；
- T011：/mfa/verify 的限流 + used_step 防重放（90s 窗口内不可重放）；
- T012：绑定 / 解绑的通知降级与 FR-23 审计落点；
- 横切：审计失败绝不阻断主流程（fail-open）、detail 自动脱敏。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.security import mfa_gate as mg
from app.security import mfa_policy as mp
from app.security.redaction import MASK

from app.security.mfa_gate import (
    AUDIT_MFA_DISABLE,
    AUDIT_MFA_ENABLE,
    AUDIT_MFA_LOCKED,
    AUDIT_MFA_REPLAY,
    AUDIT_MFA_VERIFY_FAIL,
    AUDIT_MFA_VERIFY_OK,
    DECISION_ALLOW,
    DECISION_DENY,
)

TENANT = "tenant-0001"
ADMIN = "admin@corp.example"
IP = "203.0.113.7"
#: 固定的 Unix 秒基准；所有限流 / 防重放断言都相对它构造。
FIXED_NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# 内存 fake：最小可用 motor 兼容层
# ---------------------------------------------------------------------------


def _matches(doc: dict, query: dict) -> bool:
    """支持等值比较与 $gt / $gte / $lt / $lte / $ne 的最小查询语义。"""
    for key, expected in (query or {}).items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$gt" and not (actual is not None and actual > operand):
                    return False
                if op == "$gte" and not (actual is not None and actual >= operand):
                    return False
                if op == "$lt" and not (actual is not None and actual < operand):
                    return False
                if op == "$lte" and not (actual is not None and actual <= operand):
                    return False
                if op == "$ne" and actual == operand:
                    return False
        elif actual != expected:
            return False
    return True


class _AsyncCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self) -> "_AsyncCursor":
        self._it = iter(self._docs)
        return self

    async def __anext__(self) -> dict:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    """覆盖 mfa_gate / audit_events 用到的全部 motor 方法。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: list[dict] = []
        self.indexes: list[tuple] = []
        self.fail_find_one = False
        self.fail_insert_one = False
        self.fail_mark_used = False

    async def find_one(self, query: dict, projection=None) -> dict | None:
        if self.fail_find_one:
            raise RuntimeError("mongo down")
        for doc in self.docs:
            if _matches(doc, query or {}):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        if self.fail_insert_one:
            raise RuntimeError("mongo down")
        self.docs.append(dict(doc))

    async def insert_many(self, docs: list[dict], ordered: bool = True, **kw: Any) -> None:
        for doc in docs:
            await self.insert_one(doc)

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        target = None
        for doc in self.docs:
            if _matches(doc, query or {}):
                target = doc
                break
        if target is None:
            if not upsert:
                return
            target = dict(query)
            self.docs.append(target)
        target.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            target.pop(key, None)

    async def delete_one(self, query: dict) -> None:
        for i, doc in enumerate(self.docs):
            if _matches(doc, query or {}):
                del self.docs[i]
                return

    async def delete_many(self, query: dict) -> None:
        self.docs = [d for d in self.docs if not _matches(d, query or {})]

    async def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.indexes.append((args, kwargs))

    def find(self, query: dict, *args: Any, **kwargs: Any) -> _AsyncCursor:
        matched = [dict(d) for d in self.docs if _matches(d, query or {})]
        return _AsyncCursor(matched)


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection(name))

    @property
    def audit_events(self) -> FakeCollection:
        return self._collections.setdefault("audit_events", FakeCollection("audit_events"))

    @property
    def mfa_lockouts(self) -> FakeCollection:
        return self._collections.setdefault("mfa_lockouts", FakeCollection("mfa_lockouts"))

    @property
    def mfa_used_steps(self) -> FakeCollection:
        return self._collections.setdefault("mfa_used_steps", FakeCollection("mfa_used_steps"))


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch) -> float:
    """固定时钟：300s 限流窗口与 90s 防重放窗口都需要可预测的时间基准。"""
    monkeypatch.setattr(mg.mp, "_now_epoch", lambda: FIXED_NOW)
    return FIXED_NOW


def _admin_doc(role: str = "tenant_admin", *, mfa_enabled: bool = False, secret: str = "hashhash") -> dict:
    return {
        "username": ADMIN,
        "tenant_id": TENANT,
        "role_name": role,
        "mfa_enabled": mfa_enabled,
        "mfa_secret_hash": secret if mfa_enabled else "",
        "mfa_secret_encrypted": "enc" if mfa_enabled else "",
    }


class _Request:
    def __init__(self, host: str = "", forwarded: str = "") -> None:
        class _Client:
            pass

        self.client = _Client()
        self.client.host = host
        self.headers = {}
        if forwarded:
            self.headers["x-forwarded-for"] = forwarded


class _FixedVerifier:
    """按固定 counter 校验的验证器，避免依赖真实时间。"""

    def __init__(self, secret: str, base_step: int) -> None:
        self._secret = secret
        self._base_counter = int(FIXED_NOW // mp.TOTP_STEP_SECONDS) + base_step
        self.calls: list[tuple[str, str]] = []

    def __call__(self, secret: str, token: str, *, window: int = 1) -> bool:
        self.calls.append((secret, token))
        for counter in range(
                self._base_counter - window, self._base_counter + window + 1
            ):
                if _compute_totp_at(secret, counter=counter) == token:
                    return True
        return False


# ---------------------------------------------------------------------------
# client_ip_from_request / 小工具
# ---------------------------------------------------------------------------


def test_client_ip_prefers_x_forwarded_for_first_hop() -> None:
    req = _Request(host="127.0.0.1", forwarded="203.0.113.7, 10.0.0.1")
    assert mg.client_ip_from_request(req) == "203.0.113.7"


def test_client_ip_falls_back_to_connection_host() -> None:
    assert mg.client_ip_from_request(_Request(host="198.51.100.9")) == "198.51.100.9"


def test_client_ip_empty_when_request_missing() -> None:
    assert mg.client_ip_from_request(None) == ""
    assert mg.client_ip_from_request(_Request()) == ""


def test_current_totp_step_is_step_aligned() -> None:
    step = mg.current_totp_step(now=mp.TOTP_STEP_SECONDS * 41 + 7)
    assert step == 41


def test_secret_scope_carries_tenant_first_for_purge_derivation() -> None:
    scope = mg.secret_scope(user_id="u1", tenant_id=TENANT, secret_hint="abcd")
    assert scope.split("|", 1)[0] == TENANT
    assert mp.tenant_id_from_scope(scope) == TENANT


def test_account_mfa_state_reads_role_name_field() -> None:
    """admin_accounts 存的是 role_name，不是 role —— 必须能识别高权限。"""
    state = mp.AccountMfaState.from_row(_admin_doc("platform_admin"))
    assert state.role == "platform_admin"
    assert mp.is_high_privilege_role(state.role)


def _compute_totp_at(secret: str, *, counter: int) -> str:
    """RFC 6238 TOTP（HMAC-SHA1 / 30s step / 6 位），与 app.core.totp 实现一致。

    用显式 ``counter`` 而不是相对偏移，保证与时间无关、结果可重复。
    """
    stripped = secret.strip().rstrip("=")
    padded = stripped + "=" * ((8 - len(stripped) % 8) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % 10**6).zfill(6)


def _totp_at_step(secret: str, step: int, *, now: float = FIXED_NOW) -> str:
    """``step`` 为相对 ``now`` 的 30s 窗口偏移（与 app.core.totp.compute_totp 同语义）。"""
    return _compute_totp_at(secret, counter=int(now // mp.TOTP_STEP_SECONDS) + step)



# ---------------------------------------------------------------------------
# T011：FR-2 登录闸门
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_gate_not_required_for_regular_member() -> None:
    gate = await mg.evaluate_login_gate(FakeDB(), _admin_doc("member"), client_ip=IP)
    assert gate.action == mp.DECISION_NOT_REQUIRED
    assert not gate.blocks_business_access


@pytest.mark.asyncio
async def test_login_gate_requires_bind_for_high_privilege_without_mfa() -> None:
    gate = await mg.evaluate_login_gate(FakeDB(), _admin_doc("tenant_admin"), client_ip=IP)
    assert gate.action == mp.DECISION_BIND_REQUIRED
    assert gate.blocks_business_access
    assert gate.reason_code == "mfa_not_bound"
    assert gate.message  # 前端可直接展示


@pytest.mark.asyncio
async def test_login_gate_verify_required_when_high_privilege_has_mfa() -> None:
    gate = await mg.evaluate_login_gate(FakeDB(), _admin_doc("platform_admin", mfa_enabled=True), client_ip=IP)
    assert gate.action == mp.DECISION_VERIFY_REQUIRED
    assert gate.blocks_business_access
    assert gate.reason_code == "mfa_enabled"


@pytest.mark.asyncio
async def test_login_gate_locks_after_max_failures() -> None:
    db = FakeDB()
    tracker = mp.MongoMfaLockoutTracker(db)
    key = mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP)
    now = FIXED_NOW
    for _ in range(mp.MAX_FAILURES):
        await tracker.record_failure(key, now=now)

    gate = await mg.evaluate_login_gate(db, _admin_doc("tenant_admin"), client_ip=IP)
    assert gate.action == mp.DECISION_LOCKED
    assert gate.attempts_remaining == 0
    assert gate.locked_until is not None
    # 锁定时限与 FR-3 窗口一致
    assert gate.locked_until <= datetime.fromtimestamp(now + mp.LOCKOUT_WINDOW_SECONDS, tz=timezone.utc)


@pytest.mark.asyncio
async def test_login_gate_lockout_store_failure_degrades_to_unlocked() -> None:
    """MongoDB 抖动不能把所有高权限账号锁死（安全侧但可用性优先的降级）。"""
    db = FakeDB()
    db.mfa_lockouts.fail_find_one = True
    gate = await mg.evaluate_login_gate(db, _admin_doc("tenant_admin"), client_ip=IP)
    # 读不到计数 → failures=0 → 仍要求绑定，而不是直接锁定
    assert gate.action == mp.DECISION_BIND_REQUIRED


@pytest.mark.asyncio
async def test_login_gate_window_expiry_resets_failures() -> None:
    db = FakeDB()
    tracker = mp.MongoMfaLockoutTracker(db)
    key = mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP)
    base = 1_000_000.0
    for _ in range(mp.MAX_FAILURES):
        await tracker.record_failure(key, now=base)

    # 超过 300s 窗口后，计数应归零
    gate = await mg.evaluate_login_gate(db, _admin_doc("tenant_admin"), client_ip=IP)
    assert gate.action == mp.DECISION_BIND_REQUIRED
    assert gate.attempts_remaining == mp.MAX_FAILURES


@pytest.mark.asyncio
async def test_record_and_clear_mfa_failures_are_isolated_per_ip() -> None:
    db = FakeDB()
    await mg.record_mfa_failure(db, username=ADMIN, tenant_id=TENANT, client_ip="10.0.0.1")
    await mg.record_mfa_failure(db, username=ADMIN, tenant_id=TENANT, client_ip="10.0.0.2")

    # 两个 IP 维度互不影响
    await mg.clear_mfa_failures(db, username=ADMIN, tenant_id=TENANT, client_ip="10.0.0.1")
    tracker = mp.MongoMfaLockoutTracker(db)
    assert (await tracker.get(mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip="10.0.0.1"))).failures == 0
    assert (await tracker.get(mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip="10.0.0.2"))).failures == 1


# ---------------------------------------------------------------------------
# T011：FR-3 限流 + FR-4 used_step 防重放
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_totp_success_consumes_candidate_steps() -> None:
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    base_step = 1000
    verifier = _FixedVerifier(secret, base_step)

    ok, verdict = await mg.check_and_consume_totp(
        db,
        username=ADMIN,
        tenant_id=TENANT,
        code=_totp_at_step(secret, base_step),
        raw_secret=secret,
        client_ip=IP,
        step=base_step,
        verifier=verifier,
        secret_hint="hint1",
    )

    assert ok is True
    assert verdict.reason_code == "totp_verified"
    # 校验窗口内的每一个候选 step 都被消费（防重放的核心保证）
    expected_scope = f"{TENANT}|{ADMIN}|hint1"
    stored_steps = sorted(doc["step"] for doc in db.mfa_used_steps.docs)
    assert stored_steps == list(mp.candidate_steps(base_step))
    assert all(doc["scope"] == expected_scope for doc in db.mfa_used_steps.docs)
    assert verifier.calls == [(secret, _totp_at_step(secret, base_step))]


@pytest.mark.asyncio
async def test_totp_success_sets_ttl_matching_90s_window() -> None:
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    now = FIXED_NOW
    await mg.check_and_consume_totp(
        db,
        username=ADMIN,
        tenant_id=TENANT,
        code=_totp_at_step("JBSWY3DPEHPK3PXP", 1001),
        raw_secret=secret,
        step=1001,
        now=now,
        verifier=_FixedVerifier(secret, 1001),
        secret_hint="hint1",
    )
    expires = [doc["expires_at"] for doc in db.mfa_used_steps.docs]
    assert expires and all(
        abs((dt - datetime.fromtimestamp(now, tz=timezone.utc)).total_seconds() - mp.TOTP_USED_STEP_TTL_SECONDS) < 1e-6
        for dt in expires
    )


@pytest.mark.asyncio
async def test_totp_success_records_tenant_id_for_purge() -> None:
    db = FakeDB()
    await mg.check_and_consume_totp(
        db,
        username=ADMIN,
        tenant_id=TENANT,
        code=_totp_at_step("JBSWY3DPEHPK3PXP", 1002),
        raw_secret="JBSWY3DPEHPK3PXP",
        step=1002,
        verifier=_FixedVerifier("JBSWY3DPEHPK3PXP", 1002),
        secret_hint="hint1",
    )
    assert db.mfa_used_steps.docs and all(doc.get("tenant_id") == TENANT for doc in db.mfa_used_steps.docs)


@pytest.mark.asyncio
async def test_totp_replay_blocked_within_90s_window() -> None:
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    code = _totp_at_step(secret, 1003)
    common = dict(username=ADMIN, tenant_id=TENANT, code=code, raw_secret=secret,
                  client_ip=IP, step=1003, verifier=_FixedVerifier(secret, 1003), secret_hint="hint1")

    ok1, verdict1 = await mg.check_and_consume_totp(db, **common)
    assert ok1 is True

    ok2, verdict2 = await mg.check_and_consume_totp(db, **common)
    assert ok2 is False
    assert verdict2.reason_code == "replay_blocked"
    assert verdict2.message


@pytest.mark.asyncio
async def test_totp_next_window_is_allowed_again() -> None:
    """窗口滑过后同一 secret 的下一个 step 可以再次使用（防重放不是永久封锁）。"""
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    common = dict(username=ADMIN, tenant_id=TENANT, raw_secret=secret,
                  client_ip=IP, secret_hint="hint1")

    ok1, _ = await mg.check_and_consume_totp(
        db, code=_totp_at_step(secret, 1004), step=1004,
        verifier=_FixedVerifier(secret, 1004), **common,
    )
    assert ok1 is True

    # 把 used_step 的过期时间拨到过去，模拟 90s 窗口结束
    for doc in db.mfa_used_steps.docs:
        doc["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    ok2, verdict2 = await mg.check_and_consume_totp(
        db, code=_totp_at_step(secret, 1005), step=1005,
        verifier=_FixedVerifier(secret, 1005), **common,
    )
    assert ok2 is True, verdict2


@pytest.mark.asyncio
async def test_totp_invalid_code_records_failure_and_auditable_reason() -> None:
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    ok, verdict = await mg.check_and_consume_totp(
        db, username=ADMIN, tenant_id=TENANT, code="000000", raw_secret=secret,
        client_ip=IP, step=1006, verifier=_FixedVerifier(secret, 1006), secret_hint="hint1",
    )
    assert ok is False
    assert verdict.reason_code == "totp_invalid"
    # 失败计数 +1，且没有消费任何 used_step
    tracker = mp.MongoMfaLockoutTracker(db)
    assert (await tracker.get(mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP))).failures == 1
    assert db.mfa_used_steps.docs == []


@pytest.mark.asyncio
async def test_totp_locks_after_max_failures_without_consuming_steps() -> None:
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    key = mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP)
    tracker = mp.MongoMfaLockoutTracker(db)
    now = FIXED_NOW
    for _ in range(mp.MAX_FAILURES):
        await tracker.record_failure(key, now=now)

    ok, verdict = await mg.check_and_consume_totp(
        db, username=ADMIN, tenant_id=TENANT, code=_totp_at_step(secret, 1007),
        raw_secret=secret, client_ip=IP, step=1007, now=FIXED_NOW,
        verifier=_FixedVerifier(secret, 1007), secret_hint="hint1",
    )
    assert ok is False
    assert verdict.action == mp.DECISION_LOCKED
    assert verdict.reason_code == "rate_limited"
    # 锁定时不应消耗 step（否则攻击者可以用正确 code 探测锁定状态）
    assert db.mfa_used_steps.docs == []


@pytest.mark.asyncio
async def test_totp_lockout_check_comes_before_verifier_call() -> None:
    """锁定时验证器不应被调用 —— 避免向攻击者泄漏「code 是否有效」。"""
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    key = mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP)
    tracker = mp.MongoMfaLockoutTracker(db)
    for _ in range(mp.MAX_FAILURES):
        await tracker.record_failure(key, now=FIXED_NOW)

    verifier = _FixedVerifier(secret, 1008)
    await mg.check_and_consume_totp(
        db, username=ADMIN, tenant_id=TENANT, code=_totp_at_step(secret, 1008),
        raw_secret=secret, client_ip=IP, step=1008, now=FIXED_NOW,
        verifier=verifier, secret_hint="hint1",
    )
    assert verifier.calls == []


@pytest.mark.asyncio
async def test_totp_used_step_store_failure_is_fail_open_and_logged() -> None:
    """used_step 存储故障时不阻断登录（可用性），但必须留 warning 日志。"""
    db = FakeDB()
    db.mfa_used_steps.fail_find_one = True
    secret = "JBSWY3DPEHPK3PXP"
    ok, verdict = await mg.check_and_consume_totp(
        db, username=ADMIN, tenant_id=TENANT, code=_totp_at_step(secret, 1009),
        raw_secret=secret, client_ip=IP, step=1009,
        verifier=_FixedVerifier(secret, 1009), secret_hint="hint1",
    )
    assert ok is True
    assert verdict.reason_code == "totp_verified"


@pytest.mark.asyncio
async def test_totp_failure_record_failure_raises_bubbles_up() -> None:
    """限流写入失败属存储层故障：必须向上抛，不能静默放行。"""
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    original_update = db.mfa_lockouts.update_one

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("mongo write failed")

    db.mfa_lockouts.update_one = _boom  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="mongo write failed"):
        await mg.check_and_consume_totp(
            db, username=ADMIN, tenant_id=TENANT, code="000000", raw_secret=secret,
            client_ip=IP, step=1010, verifier=_FixedVerifier(secret, 1010), secret_hint="hint1",
        )
    db.mfa_lockouts.update_one = original_update  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# T012 + FR-23：审计落点
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_mfa_audit_persists_tamper_evident_chain() -> None:
    db = FakeDB()
    ok = await mg.emit_mfa_audit(
        db, tenant_id=TENANT, actor_id=ADMIN,
        action=AUDIT_MFA_DISABLE, decision=DECISION_ALLOW, target_id=ADMIN,
        detail={"password": "SuperSecret123!", "role": "tenant_admin"},
        client_ip=IP,
    )
    assert ok is True
    assert len(db.audit_events.docs) == 2  # 事件 + 链游标
    event = next(d for d in db.audit_events.docs if d.get("action") == AUDIT_MFA_DISABLE)

    # 审计链自洽（seq=1，prev_hash=None，hash 可验）
    from app.security.audit_events import AuditEvent, AuditEventRepository

    repo = AuditEventRepository(db, source_service=mg.SOURCE_SERVICE)
    result = await repo.verify_chain()
    assert result.ok is True, result.summary

    # detail 自动脱敏（FR-23 与 FR-20 联动）
    assert event["detail"]["password"] != "SuperSecret123!"
    assert event["detail"]["password"] == MASK
    assert event["tenant_id"] == TENANT
    assert event["actor_id"] == ADMIN
    assert event["client_ip"] == IP
    assert event["source_service"] == mg.SOURCE_SERVICE
    assert event["seq"] == 1


@pytest.mark.asyncio
async def test_emit_mfa_audit_failure_never_raises() -> None:
    """审计链路故障不能阻断登录 / 解绑主流程。"""
    db = FakeDB()
    db.audit_events.fail_insert_one = True
    ok = await mg.emit_mfa_audit(
        db, tenant_id=TENANT, actor_id=ADMIN, action=AUDIT_MFA_VERIFY_FAIL, decision=DECISION_DENY,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_notify_mfa_change_degrades_to_audit_when_no_channel() -> None:
    """OQ-1：通知通道未接入时降级为审计事件，且可取证。"""
    db = FakeDB()
    result = await mg.notify_mfa_change(
        db, tenant_id=TENANT, username=ADMIN, event_type="mfa_disabled",
        detail={"role": "tenant_admin", "high_privilege_account": True},
        client_ip=IP,
    )
    assert result == {
        "notified": False,
        "degraded": True,
        "reason": mg.NOTIFICATION_NOT_CONNECTED,
        "audit": True,
    }
    actions = [d.get("action") for d in db.audit_events.docs if d.get("action")]
    assert actions == [AUDIT_MFA_DISABLE]
    event = next(d for d in db.audit_events.docs if d.get("action") == AUDIT_MFA_DISABLE)
    assert event["detail"]["event_type"] == "mfa_disabled"
    assert event["detail"]["high_privilege_account"] is True


@pytest.mark.asyncio
async def test_notify_mfa_change_accepts_custom_action_and_decision() -> None:
    db = FakeDB()
    await mg.notify_mfa_change(
        db, tenant_id=TENANT, username=ADMIN, event_type="mfa_enabled",
        audit_action=AUDIT_MFA_ENABLE, decision=DECISION_ALLOW,
    )
    event = next(d for d in db.audit_events.docs if d.get("action") == AUDIT_MFA_ENABLE)
    assert event["decision"] == DECISION_ALLOW
    assert event["detail"]["event_type"] == "mfa_enabled"


@pytest.mark.asyncio
async def test_notify_mfa_change_uses_channel_when_provided() -> None:
    sent: list[dict] = []

    def channel(*, tenant_id: str, username: str, event_type: str, detail: dict) -> None:
        sent.append({"tenant_id": tenant_id, "username": username, "event_type": event_type, "detail": detail})

    db = FakeDB()
    result = await mg.notify_mfa_change(
        db, tenant_id=TENANT, username=ADMIN, event_type="mfa_enabled",
        detail={"role": "platform_admin"}, audit_action=AUDIT_MFA_ENABLE, channel=channel,
    )
    assert result["notified"] is True and result["degraded"] is False and result["reason"] == ""
    assert len(sent) == 1
    assert sent[0]["event_type"] == "mfa_enabled"
    # 通道成功时审计事件仍要落（双写，不是二选一）
    assert any(d["action"] == AUDIT_MFA_ENABLE for d in db.audit_events.docs)


@pytest.mark.asyncio
async def test_notify_mfa_change_degrades_when_channel_raises() -> None:
    db = FakeDB()

    def broken_channel(*, tenant_id: str, username: str, event_type: str, detail: dict) -> None:
        raise RuntimeError("smtp down")

    result = await mg.notify_mfa_change(
        db, tenant_id=TENANT, username=ADMIN, event_type="mfa_disabled",
        audit_action=AUDIT_MFA_DISABLE, channel=broken_channel,
    )
    assert result["notified"] is False
    assert result["degraded"] is True
    assert result["reason"] == "notification send failed"
    assert result["audit"] is True


@pytest.mark.asyncio
async def test_audit_chain_survives_multiple_mfa_events() -> None:
    """连续多次 MFA 事件仍构成一条完整哈希链（防篡改取证）。"""
    db = FakeDB()
    secret = "JBSWY3DPEHPK3PXP"
    for _ in range(3):
        await mg.emit_mfa_audit(
            db, tenant_id=TENANT, actor_id=ADMIN, action=AUDIT_MFA_VERIFY_FAIL, decision=DECISION_DENY,
            detail={"reason_code": "totp_invalid"},
        )

    from app.security.audit_events import AuditEventRepository

    repo = AuditEventRepository(db, source_service=mg.SOURCE_SERVICE)
    result = await repo.verify_chain()
    assert result.ok is True, result.summary
    events = [d for d in db.audit_events.docs if d.get("action") == AUDIT_MFA_VERIFY_FAIL]
    assert [d["seq"] for d in events] == [1, 2, 3]
    # 链式引用：每条 prev_hash 等于上一条 event_hash
    for prev, cur in zip(events, events[1:]):
        assert cur["prev_hash"] == prev["event_hash"]


@pytest.mark.asyncio
async def test_audit_denied_disable_still_records_when_password_wrong() -> None:
    """口令错误的解绑尝试也必须可取证（审计 decision=deny）。"""
    db = FakeDB()
    await mg.emit_mfa_audit(
        db, tenant_id=TENANT, actor_id=ADMIN, action=AUDIT_MFA_DISABLE,
        decision=DECISION_DENY, target_id=ADMIN, detail={"reason_code": "wrong_password"},
    )
    event = next(d for d in db.audit_events.docs if d.get("action") == AUDIT_MFA_DISABLE)
    assert event["decision"] == DECISION_DENY
    assert event["detail"]["reason_code"] == "wrong_password"


# ---------------------------------------------------------------------------
# 锁定期消息 / 文案一致性（前端依赖）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_decision_surfaces_attempts_remaining_zero() -> None:
    db = FakeDB()
    tracker = mp.MongoMfaLockoutTracker(db)
    key = mp.failure_key(username=ADMIN, tenant_id=TENANT, client_ip=IP)
    for _ in range(mp.MAX_FAILURES):
        await tracker.record_failure(key, now=FIXED_NOW)
    gate = await mg.evaluate_login_gate(db, _admin_doc("platform_admin", mfa_enabled=True), client_ip=IP)
    assert gate.action == mp.DECISION_LOCKED
    assert gate.attempts_remaining == 0
    assert gate.message == mp.LOCKED_MESSAGE
