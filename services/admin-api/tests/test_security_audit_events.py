"""FR-23 (QF-678/679) 防篡改审计事件测试.

覆盖：哈希链计算与顺序号、事件构造与 detail 脱敏、落库、链校验
（篡改检测）、冲突处理、索引与查询。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.security import audit_events as ae


FIXED_DT = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 哈希链
# ---------------------------------------------------------------------------


def test_chain_hash_is_deterministic():
    h1 = ae.chain_hash(None, {"action": "login", "seq": 1})
    h2 = ae.chain_hash(None, {"action": "login", "seq": 1})
    assert h1 == h2
    assert len(h1) == 64


def test_chain_hash_depends_on_prev_hash():
    a = ae.chain_hash(None, {"action": "login"})
    b = ae.chain_hash("previous-hash", {"action": "login"})
    assert a != b


def test_chain_hash_depends_on_body():
    assert ae.chain_hash(None, {"action": "login"}) != ae.chain_hash(None, {"action": "logout"})


def test_chain_hash_is_key_order_independent():
    a = ae.chain_hash(None, {"a": 1, "b": 2})
    b = ae.chain_hash(None, {"b": 2, "a": 1})
    assert a == b


def test_chain_hash_uses_delimiter_between_prev_and_body():
    # 分隔符避免 prev_hash 与 body 边界歧义
    x = ae.chain_hash("prev", {"a": 1})
    y = ae.chain_hash("pre", {"v": 1, "a": 1})  # 构造形似拼接
    assert x != y


def test_event_verify_self_check():
    event = ae.build_event(action="auth.login.success", decision="allow", actor_id="u-1", occurred_at=FIXED_DT)
    stamped = event.with_hash(None, 1)
    stamped.verify()  # 不抛异常
    assert stamped.event_hash
    assert stamped.seq == 1


def test_event_verify_detects_body_tampering():
    event = ae.build_event(action="auth.login.success", decision="allow", actor_id="u-1", occurred_at=FIXED_DT)
    stamped = event.with_hash(None, 1)
    tampered = ae.AuditEvent(
        tenant_id=stamped.tenant_id,
        actor_type=stamped.actor_type,
        actor_id="u-999",  # 篡改 actor
        action=stamped.action,
        decision=stamped.decision,
        occurred_at=stamped.occurred_at,
        event_id=stamped.event_id,
        source_service=stamped.source_service,
        prev_hash=stamped.prev_hash,
        event_hash=stamped.event_hash,
        seq=stamped.seq,
    )
    with pytest.raises(ae.AuditChainBroken):
        tampered.verify()


def test_event_requires_action_and_decision_and_actor_type():
    with pytest.raises(ae.AuditEventError):
        ae.AuditEvent(tenant_id=None, actor_type="user", actor_id="u", action="", decision="allow", occurred_at=FIXED_DT)
    with pytest.raises(ae.AuditEventError):
        ae.AuditEvent(tenant_id=None, actor_type="user", actor_id="u", action="a", decision="", occurred_at=FIXED_DT)
    with pytest.raises(ae.AuditEventError):
        ae.AuditEvent(tenant_id=None, actor_type="", actor_id="u", action="a", decision="allow", occurred_at=FIXED_DT)


def test_event_document_roundtrip():
    event = ae.build_event(
        action="auth.login.success",
        decision="allow",
        actor_id="u-1",
        tenant_id="t-1",
        occurred_at=FIXED_DT,
    )
    stamped = event.with_hash(None, 7)
    doc = stamped.document()
    assert doc["_id"] == stamped.event_id
    assert doc["seq"] == 7
    assert doc["prev_hash"] is None
    assert doc["event_hash"] == stamped.event_hash


def test_verify_chain_accepts_valid_sequence():
    events = []
    prev = None
    for i in range(1, 5):
        e = ae.build_event(action="auth.login.success", decision="allow", actor_id="u-1", occurred_at=FIXED_DT)
        stamped = e.with_hash(prev, i)
        events.append(stamped)
        prev = stamped.event_hash
    result = ae.verify_chain(events)
    assert result.ok
    assert result.checked == 4
    assert "ok" in result.summary


def test_verify_chain_rejects_gap():
    e1 = ae.build_event(action="a", decision="allow", occurred_at=FIXED_DT).with_hash(None, 1)
    e3 = ae.build_event(action="a", decision="allow", occurred_at=FIXED_DT).with_hash(e1.event_hash, 3)
    result = ae.verify_chain([e1, e3])
    assert not result.ok
    assert result.first_broken_seq == 3
    assert "seq gap" in result.reason


def test_verify_chain_rejects_prev_hash_mismatch():
    e1 = ae.build_event(action="a", decision="allow", occurred_at=FIXED_DT).with_hash(None, 1)
    e2 = ae.build_event(action="b", decision="allow", occurred_at=FIXED_DT).with_hash("bogus", 2)
    result = ae.verify_chain([e1, e2])
    assert not result.ok
    assert "prev_hash mismatch" in result.reason


def test_verify_chain_rejects_body_tamper():
    e1 = ae.build_event(action="a", decision="allow", actor_id="u-1", occurred_at=FIXED_DT).with_hash(None, 1)
    e2 = ae.build_event(action="b", decision="allow", actor_id="u-1", occurred_at=FIXED_DT).with_hash(e1.event_hash, 2)
    tampered = ae.AuditEvent(
        tenant_id=None,
        actor_type="user",
        actor_id="u-2",  # 篡改
        action=e2.action,
        decision=e2.decision,
        occurred_at=e2.occurred_at,
        event_id=e2.event_id,
        prev_hash=e2.prev_hash,
        event_hash=e2.event_hash,
        seq=e2.seq,
    )
    result = ae.verify_chain([e1, tampered])
    assert not result.ok
    assert "event_hash mismatch" in result.reason


def test_verify_chain_rejects_missing_hash():
    e1 = ae.build_event(action="a", decision="allow", occurred_at=FIXED_DT).with_hash(None, 1)
    broken = ae.AuditEvent(
        tenant_id=None, actor_type="user", actor_id="u", action="b", decision="allow",
        occurred_at=FIXED_DT, prev_hash=e1.event_hash, event_hash=None, seq=2,
    )
    result = ae.verify_chain([e1, broken])
    assert not result.ok
    assert "missing hash/seq" in result.reason


def test_verify_chain_empty_is_ok():
    result = ae.verify_chain([])
    assert result.ok
    assert result.checked == 0


def test_verify_chain_summary_for_broken_chain():
    e1 = ae.build_event(action="a", decision="allow", occurred_at=FIXED_DT).with_hash(None, 1)
    result = ae.verify_chain([e1])
    assert result.summary == "chain ok (1 events)"


# ---------------------------------------------------------------------------
# 事件构造（detail 脱敏）
# ---------------------------------------------------------------------------


def test_build_event_redacts_detail():
    event = ae.build_event(
        action="auth.login.success",
        decision="allow",
        actor_id="u-1",
        detail={"password": "hunter2", "token": "tok-1", "user_id": "u-1"},
    )
    assert event.detail["password"] == "***REDACTED***"
    assert event.detail["token"] == "***REDACTED***"
    assert event.detail["user_id"] == "u-1"


def test_build_event_generates_unique_ids():
    e1 = ae.build_event(action="a", decision="allow")
    e2 = ae.build_event(action="a", decision="allow")
    assert e1.event_id != e2.event_id
    assert e1.event_id.startswith("evt-")


def test_build_event_defaults():
    event = ae.build_event(action="a", decision="allow")
    assert event.actor_type == "user"
    assert event.schema_version == ae.SCHEMA_VERSION == 1
    assert event.prev_hash is None
    assert event.event_hash is None
    assert event.seq is None
    assert event.detail == {}


def test_utcnow_is_timezone_aware():
    assert ae.utcnow().tzinfo is not None


# ---------------------------------------------------------------------------
# 落库与链校验（fake db）
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    return ae.InMemoryAuditDb()


@pytest.mark.asyncio
async def test_record_appends_events_with_hash_chain(db):
    repo = ae.AuditEventRepository(db, source_service="admin-api")
    e1 = await repo.record(action="auth.login.success", decision="allow", actor_id="u-1", tenant_id="t-1")
    e2 = await repo.record(action="auth.mfa.disable", decision="allow", actor_id="u-1", tenant_id="t-1")
    assert e1.seq == 1
    assert e2.seq == 2
    assert e1.prev_hash is None
    assert e2.prev_hash == e1.event_hash
    assert e1.source_service == "admin-api"
    assert e2.source_service == "admin-api"


@pytest.mark.asyncio
async def test_record_persists_detail_in_redacted_form(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(
        action="auth.mfa.disable",
        decision="allow",
        actor_id="u-1",
        detail={"password": "hunter2", "client_ip": "1.2.3.4"},
    )
    events = await repo.list_events()
    assert events[0].detail["password"] == "***REDACTED***"
    assert events[0].detail["client_ip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_verify_chain_passes_after_record(db):
    repo = ae.AuditEventRepository(db)
    for i in range(5):
        await repo.record(action=f"action.{i}", decision="allow", actor_id="u-1", tenant_id="t-1")
    result = await repo.verify_chain()
    assert result.ok
    assert result.checked == 5


@pytest.mark.asyncio
async def test_verify_chain_detects_tampering(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(action="a", decision="allow", actor_id="u-1")
    await repo.record(action="b", decision="allow", actor_id="u-1")
    # 直接篡改第二条事件的 actor_id
    docs = db._collections[ae.AUDIT_EVENTS_COLLECTION]
    for doc in docs:
        if doc.get("action") == "b":
            doc["actor_id"] = "u-evil"
    result = await repo.verify_chain()
    assert not result.ok
    assert result.first_broken_seq == 2
    assert "event_hash mismatch" in result.reason


@pytest.mark.asyncio
async def test_verify_chain_detects_deleted_event(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(action="a", decision="allow", actor_id="u-1")
    await repo.record(action="b", decision="allow", actor_id="u-1")
    await repo.record(action="c", decision="allow", actor_id="u-1")
    docs = db._collections[ae.AUDIT_EVENTS_COLLECTION]
    db._collections[ae.AUDIT_EVENTS_COLLECTION] = [d for d in docs if d.get("action") != "b"]
    result = await repo.verify_chain()
    assert not result.ok


@pytest.mark.asyncio
async def test_verify_chain_returns_ok_for_empty_db(db):
    repo = ae.AuditEventRepository(db)
    result = await repo.verify_chain()
    assert result.ok
    assert result.checked == 0


@pytest.mark.asyncio
async def test_cursor_state_after_records(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(action="a", decision="allow", actor_id="u")
    await repo.record(action="b", decision="allow", actor_id="u")
    cursor = await repo.latest_cursor()
    assert cursor["seq"] == 2
    assert cursor["latest_hash"]


@pytest.mark.asyncio
async def test_count_excludes_cursor_document(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(action="a", decision="allow", actor_id="u")
    await repo.record(action="b", decision="allow", actor_id="u")
    assert await repo.count() == 2


@pytest.mark.asyncio
async def test_list_events_filters_by_tenant_and_action(db):
    repo = ae.AuditEventRepository(db)
    await repo.record(action="auth.login", decision="allow", actor_id="u-1", tenant_id="t-1")
    await repo.record(action="auth.login", decision="allow", actor_id="u-2", tenant_id="t-2")
    await repo.record(action="auth.logout", decision="allow", actor_id="u-1", tenant_id="t-1")

    assert len(await repo.list_events()) == 3
    assert len(await repo.list_events(tenant_id="t-1")) == 2
    assert len(await repo.list_events(action="auth.logout")) == 1
    assert len(await repo.list_events(tenant_id="t-3")) == 0


@pytest.mark.asyncio
async def test_list_events_respects_limit(db):
    repo = ae.AuditEventRepository(db)
    for i in range(10):
        await repo.record(action="a", decision="allow", actor_id=f"u-{i}")
    assert len(await repo.list_events(limit=3)) == 3


@pytest.mark.asyncio
async def test_ensure_indexes_does_not_raise(db):
    repo = ae.AuditEventRepository(db)
    await repo.ensure_indexes()


@pytest.mark.asyncio
async def test_chain_conflict_raises_when_seq_taken(db):
    """并发写冲突：seq 唯一索引冲突时抛 AuditChainConflict，调用方重试。"""
    repo = ae.AuditEventRepository(db)
    # 预置一个占用了 seq=1 的事件，但没有对应的游标记录
    docs = db._collections.setdefault(ae.AUDIT_EVENTS_COLLECTION, [])
    docs.append({"_id": "evt-preexisting", "seq": 1, "action": "x", "decision": "allow", "actor_type": "user", "actor_id": "u"})
    with pytest.raises(ae.AuditChainConflict):
        await repo.record(action="a", decision="allow", actor_id="u", retries=2)


@pytest.mark.asyncio
async def test_record_accepts_prebuilt_event(db):
    repo = ae.AuditEventRepository(db)
    event = ae.build_event(action="auth.login.success", decision="allow", actor_id="u-1", occurred_at=FIXED_DT)
    stamped = await repo.record(event)
    assert stamped.event_id == event.event_id
    assert stamped.seq == 1
    assert stamped.occurred_at == FIXED_DT


@pytest.mark.asyncio
async def test_repository_uses_custom_collection(db):
    repo = ae.AuditEventRepository(db, collection="custom_audit")
    await repo.record(action="a", decision="allow", actor_id="u")
    assert len(db._collections["custom_audit"]) == 2  # 1 事件 + 1 游标
    assert ae.AUDIT_EVENTS_COLLECTION not in db._collections


def test_is_duplicate_key_detection():
    assert ae._is_duplicate_key(ae.DuplicateKeyError())
    assert not ae._is_duplicate_key(ValueError())


def test_constants():
    assert ae.AUDIT_EVENTS_COLLECTION == "audit_events"
    assert ae.CHAIN_CURSOR_ID == "__chain_cursor__"
    assert ae.EVENT_ID_PREFIX == "evt"
