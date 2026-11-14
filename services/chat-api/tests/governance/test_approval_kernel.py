"""056 — ApprovalKernel 单测（纯内存 fake，不依赖真实 Mongo / motor）。

覆盖 spec 056 的验收要点：
* 三类来源（tool/portal/sop）统一签发与待办视图（US1 / R-1）
* revision 原子条件更新仲裁、取消与决策并发竞态幂等（R-2 / US2）
* 身份一致性校验（R-5）、改派出口补齐（R-4）
* 审计事件统一汇入 gate_events + 前缀区分来源（R-6 / US3）
* 超时 fail-closed、审计失败 fail-open 降级、多租户隔离（E3 / US3）
"""

from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# 以单文件方式加载内核，绕开 app.governance.__init__ 的重依赖；同时让
# `from app.common.shared_constants import utc_now` 可解析。
_SERVICE_ROOT = str(Path(__file__).resolve().parents[2])
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

_KERNEL_PATH = Path(_SERVICE_ROOT) / "app" / "governance" / "approval_kernel.py"
_spec = importlib.util.spec_from_file_location("approval_kernel_under_test", _KERNEL_PATH)
ak = importlib.util.module_from_spec(_spec)
sys.modules["approval_kernel_under_test"] = ak
_spec.loader.exec_module(ak)

ApprovalKernel = ak.ApprovalKernel
ApprovalSource = ak.ApprovalSource
ApprovalState = ak.ApprovalState
ApprovalConflictError = ak.ApprovalConflictError
ApprovalActorMismatchError = ak.ApprovalActorMismatchError
ApprovalNotFoundError = ak.ApprovalNotFoundError

FIXED_NOW = datetime(2026, 11, 12, 9, 0, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, modified_count: int = 0, inserted_id: str = "") -> None:
        self.modified_count = modified_count
        self.inserted_id = inserted_id


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def to_list(self, length: int | None = None) -> list[dict]:
        rows = [dict(r) for r in self._rows]
        return rows[:length] if length else rows


def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if not any(op.startswith("$") for op in cond) and value != cond:
                return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    """支持内核所用最小 Mongo 子集：insert_one / find_one / find / update_one。"""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.fail_inserts = False
        self.before_update = None  # 并发注入钩子：update_one 前篡改文档

    async def insert_one(self, doc: dict) -> _Result:
        if self.fail_inserts:
            raise RuntimeError("simulated audit storage outage")
        row = dict(doc)
        row.setdefault("_id", uuid.uuid4().hex)
        self.docs[row["_id"]] = row
        return _Result(inserted_id=row["_id"])

    async def find_one(self, query: dict) -> dict | None:
        for row in self.docs.values():
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query: dict) -> _Cursor:
        return _Cursor([r for r in self.docs.values() if _matches(r, query)])

    async def update_one(self, flt: dict, update: dict) -> _Result:
        if self.before_update is not None:
            self.before_update(self.docs)  # 模拟另一个路径先落库
            self.before_update = None
        for _id, row in self.docs.items():
            if not _matches(row, flt):
                continue
            sets = dict(update.get("$set") or {})
            incs = dict(update.get("$inc") or {})
            unsets = list(update.get("$unset") or {})
            for k, v in sets.items():
                row[k] = v
            for k, v in incs.items():
                row[k] = int(row.get(k) or 0) + v
            for k in unsets:
                row.pop(k, None)
            self.docs[_id] = row
            return _Result(modified_count=1)
        return _Result(modified_count=0)


class FakeDB:
    def __init__(self) -> None:
        self._colls: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._colls.setdefault(name, FakeCollection())


@pytest.fixture
def env():
    db = FakeDB()
    clock = lambda: FIXED_NOW  # noqa: E731
    kernel = ApprovalKernel(db=db, audit_db=db, clock=clock)
    return types.SimpleNamespace(
        db=db, kernel=kernel, tickets=db[ak.TICKETS_COLLECTION],
        events=db[ak.GATE_EVENTS_COLLECTION], clock=clock,
    )


def _future(**kw) -> datetime:
    return FIXED_NOW + timedelta(**kw)


async def _issue(env, *, source=ApprovalSource.TOOL, source_id="act-1", tenant="t-1",
                 actor="requester-1", approver="approver-1", deadline=None, **extra):
    return await env.kernel.issue(
        source=source, source_id=source_id, tenant_id=tenant, actor_id=actor,
        approver_id=approver, deadline=deadline or _future(minutes=5), **extra,
    )


# ── R-1 / US1：签发 + 三来源统一待办 ───────────────────────────────
@pytest.mark.asyncio
async def test_issue_writes_ticket_and_audit(env):
    ticket = await _issue(env)
    assert ticket.state is ApprovalState.PENDING and ticket.revision == 0
    assert ticket.token and len(ticket.token) > 10
    doc = await env.tickets.find_one({"ticket_id": ticket.ticket_id})
    assert doc["token_hash"] == ak._token_hash(ticket.token)
    assert doc["state"] == "pending" and doc["source"] == "tool"
    events = await env.events.find({}).to_list()
    assert len(events) == 1
    assert events[0]["tool"] == "approval.tool.issued"
    assert events[0]["layer"] == "approval_kernel"
    assert events[0]["source_service"] == "chat-api"
    detail = events[0]["detail"]
    for field in ("source_id", "run_id", "node_id", "previous_state", "new_state", "actor_id"):
        assert field in detail


@pytest.mark.asyncio
async def test_list_todos_unifies_three_sources(env):
    for src, sid in [(ApprovalSource.TOOL, "t-1"), (ApprovalSource.PORTAL, "p-1"),
                     (ApprovalSource.SOP, "s-1")]:
        await _issue(env, source=src, source_id=sid, approver="approver-1")
        await _issue(env, source=src, source_id=sid + "-other", approver="someone-else")
    todos = await env.kernel.list_todos(tenant_id="t-1", approver_id="approver-1")
    assert len(todos) == 3
    assert {t.source_type for t in todos} == {"tool", "portal", "sop"}
    assert all(t.state == "pending" for t in todos)


@pytest.mark.asyncio
async def test_list_todos_status_all_vs_pending(env):
    ticket = await _issue(env)
    await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                            token=ticket.token, actor_id="approver-1", approved=True)
    pending = await env.kernel.list_todos(tenant_id="t-1", approver_id="approver-1")
    all_rows = await env.kernel.list_todos(tenant_id="t-1", approver_id="approver-1", status="all")
    assert pending == []
    assert len(all_rows) == 1 and all_rows[0].state == "approved"


# ── R-5：身份一致性 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_decide_actor_mismatch_rejected(env):
    ticket = await _issue(env)
    with pytest.raises(ApprovalActorMismatchError) as exc:
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=ticket.token, actor_id="intruder", approved=True)
    assert exc.value.code == "approval.actor_mismatch"
    doc = await env.tickets.find_one({"ticket_id": ticket.ticket_id})
    assert doc["state"] == "pending"  # 无副作用


@pytest.mark.asyncio
async def test_decide_wrong_token_not_found(env):
    await _issue(env)
    with pytest.raises(ApprovalNotFoundError):
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token="forged", actor_id="approver-1", approved=True)


# ── R-1 / R-6：决策 + 审计 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_decide_approve_and_deny(env):
    t1 = await _issue(env, source_id="approve-me")
    out = await env.kernel.decide(source=ApprovalSource.TOOL, source_id="approve-me",
                                  tenant_id="t-1", token=t1.token, actor_id="approver-1",
                                  approved=True, reason="looks good")
    assert out.ok and out.state is ApprovalState.APPROVED and out.revision == 1

    t2 = await _issue(env, source_id="deny-me")
    out2 = await env.kernel.decide(source=ApprovalSource.TOOL, source_id="deny-me",
                                   tenant_id="t-1", token=t2.token, actor_id="approver-1",
                                   approved=False, reason="not allowed")
    assert out2.ok and out2.state is ApprovalState.DENIED
    actions = sorted(e["tool"] for e in await env.events.find({}).to_list())
    assert actions == [
        "approval.tool.decided", "approval.tool.denied",
        "approval.tool.issued", "approval.tool.issued",
    ]
    denied = [e for e in await env.events.find({}).to_list() if e["tool"].endswith("denied")]
    assert denied[0]["decision"] == "deny"


# ── R-2：revision 原子条件更新 / 并发竞态 ──────────────────────────
@pytest.mark.asyncio
async def test_revision_conflict_raises_approval_conflict(env):
    ticket = await _issue(env)
    # 模拟并发路径在 CAS 之前把 revision 推进 → filter 失配 → modified_count=0
    def bump(docs):
        for row in docs.values():
            if row["ticket_id"] == ticket.ticket_id:
                row["revision"] = 99
    env.tickets.before_update = bump
    with pytest.raises(ApprovalConflictError) as exc:
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=ticket.token, actor_id="approver-1", approved=True)
    assert exc.value.code == "approval.conflict"


@pytest.mark.asyncio
async def test_cancel_then_decide_is_idempotent(env):
    ticket = await _issue(env)
    out = await env.kernel.cancel(source=ApprovalSource.TOOL, source_id="act-1",
                                  tenant_id="t-1", actor_id="requester-1")
    assert out.ok and out.state is ApprovalState.CANCELLED
    # 后到的批准：pending 票据已不存在 → NotFound（无双重生效）
    with pytest.raises(ApprovalNotFoundError):
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=ticket.token, actor_id="approver-1", approved=True)
    # 反序：决策先到，取消幂等返回一致结论
    t2 = await _issue(env, source_id="act-2")
    await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-2", tenant_id="t-1",
                            token=t2.token, actor_id="approver-1", approved=True)
    out2 = await env.kernel.cancel(source=ApprovalSource.TOOL, source_id="act-2",
                                   tenant_id="t-1", actor_id="requester-1")
    assert out2.ok is False and out2.code == "approval.already_settled"
    doc = await env.tickets.find_one({"source_id": "act-2"})
    assert doc["state"] == "approved"  # 未被取消覆盖


# ── R-4：改派 ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reassign_rotates_token_and_approver(env):
    ticket = await _issue(env, deadline=_future(minutes=1))
    new_deadline = _future(minutes=10)
    out = await env.kernel.reassign(
        source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
        new_approver_id="approver-2", actor_id="admin-1", reason="原审批人离职",
        new_deadline=new_deadline,
    )
    assert out.ok and out.state is ApprovalState.REASSIGNED
    new_token = out.detail["new_token"]
    assert new_token != ticket.token
    doc = await env.tickets.find_one({"ticket_id": ticket.ticket_id})
    assert doc["approver_id"] == "approver-2" and doc["deadline"] == new_deadline
    assert doc["token_hash"] == ak._token_hash(new_token)
    # 旧 token 立即失效
    with pytest.raises(ApprovalNotFoundError):
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=ticket.token, actor_id="approver-2", approved=True)
    # 新 token + 原审批人身份 → R-5 身份校验拒绝（票据已改派，approver 变为 approver-2）
    with pytest.raises(ApprovalActorMismatchError) as mismatch:
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=new_token, actor_id="approver-1", approved=True)
    assert mismatch.value.code == "approval.actor_mismatch"
    done = await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                   token=new_token, actor_id="approver-2", approved=True)
    assert done.ok
    assert any(e["tool"] == "approval.tool.reassigned"
               for e in await env.events.find({}).to_list())


# ── R-2：超时 fail-closed ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_timeout_fail_closed(env):
    await _issue(env, source_id="expired-1", deadline=_future(minutes=-1))
    await _issue(env, source_id="live-1", deadline=_future(minutes=5))
    n = await env.kernel.resolve_timeout(source_id="")
    assert n == 1
    expired = await env.tickets.find_one({"source_id": "expired-1"})
    live = await env.tickets.find_one({"source_id": "live-1"})
    assert expired["state"] == "expired" and live["state"] == "pending"
    timeout_events = [e for e in await env.events.find({}).to_list() if e["tool"].endswith("timeout")]
    assert len(timeout_events) == 1 and timeout_events[0]["decision"] == "deny"
    assert timeout_events[0]["detail"]["actor_id"] == "system"


@pytest.mark.asyncio
async def test_decide_after_deadline_is_fail_closed(env):
    ticket = await _issue(env, deadline=_future(minutes=-1))
    with pytest.raises(ApprovalConflictError):
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                                token=ticket.token, actor_id="approver-1", approved=True)
    doc = await env.tickets.find_one({"ticket_id": ticket.ticket_id})
    assert doc["state"] == "expired"


# ── US3：审计失败 fail-open ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_audit_failure_does_not_block_business(env, caplog):
    env.events.fail_inserts = True
    with caplog.at_level("ERROR"):
        ticket = await _issue(env)  # 审计写失败，签发仍应成功
        out = await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1",
                                      tenant_id="t-1", token=ticket.token,
                                      actor_id="approver-1", approved=True)
    assert out.ok and out.state is ApprovalState.APPROVED
    assert "approval.audit_write_failed" in caplog.text


# ── E3：多租户隔离 ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tenant_isolation(env):
    ticket = await _issue(env, tenant="tenant-A")
    with pytest.raises(ApprovalNotFoundError):
        await env.kernel.decide(source=ApprovalSource.TOOL, source_id="act-1",
                                tenant_id="tenant-B", token=ticket.token,
                                actor_id="approver-1", approved=True)
    todos_b = await env.kernel.list_todos(tenant_id="tenant-B", approver_id="approver-1")
    assert todos_b == []


# ── US2 验收：并发决策/取消 0 双重生效 ─────────────────────────────
@pytest.mark.asyncio
async def test_concurrent_cancel_and_decide_no_double_effect(env):
    """100 次并发（50 decide + 50 cancel）作用于同一票据，最终仅一个状态转换生效。"""
    import asyncio

    ticket = await _issue(env)

    async def attempt(i: int):
        try:
            if i % 2 == 0:
                return await env.kernel.decide(
                    source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                    token=ticket.token, actor_id="approver-1", approved=True,
                )
            return await env.kernel.cancel(
                source=ApprovalSource.TOOL, source_id="act-1", tenant_id="t-1",
                actor_id="requester-1",
            )
        except (ApprovalNotFoundError, ApprovalConflictError):
            return None  # 幂等拒绝 / revision 冲突，属预期

    results = await asyncio.gather(*(attempt(i) for i in range(100)))
    settled = [r for r in results if r is not None and r.ok]
    assert len(settled) == 1, f"双重生效：{len(settled)} 个状态转换成功"

    doc = await env.tickets.find_one({"ticket_id": ticket.ticket_id})
    assert doc["state"] in ("approved", "cancelled", "denied")
    # 审计只记录一次真实状态转换（issue 之外）
    transitions = [
        e for e in await env.events.find({}).to_list()
        if e["tool"].endswith(("decided", "denied", "cancelled"))
    ]
    assert len(transitions) == 1
    assert doc["revision"] == 1  # 未被二次推进


# ── R-3：审批人解析（首期仅用户型） ────────────────────────────────
def test_resolve_approver_user_type_and_role_fallback(caplog):
    assert ak.resolve_approver("u-1", "t-1") == "u-1"
    with caplog.at_level("WARNING"):
        assert ak.resolve_approver("u-1", "t-1", role_id="role-admin") == "u-1"
    assert "role_not_supported" in caplog.text
