"""001 layer 4 (approval): approver decision + requester resume are separate.

Regression guard for the 2026-10-03 audit finding: the original single-step
``validate_and_consume`` let a caller approve *its own* suspended call by simply
re-entering with the ticket — i.e. no human approval ever happened. A pending
ticket must now be decided by an approver before the requester can consume it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.governance.layers.approval import ApprovalLayer, ApprovalRegistry


class _Result:
    def __init__(self, modified=1):
        self.modified_count = modified


class _Collection:
    def __init__(self):
        self.rows: list[dict] = []

    async def insert_one(self, doc):
        row = dict(doc)
        row.setdefault("_id", f"id-{len(self.rows)}")  # Mongo assigns an _id
        self.rows.append(row)

    async def find_one(self, flt):
        for row in self.rows:
            if all(row.get(k) == v for k, v in flt.items()):
                return dict(row)
        return None

    async def update_one(self, flt, update):
        for row in self.rows:
            if all(row.get(k) == v for k, v in flt.items()):
                row.update(update.get("$set", {}))
                return _Result(1)
        return _Result(0)


class _Db:
    def __init__(self):
        self.col = _Collection()

    def __getitem__(self, name):
        return self.col


def _registry():
    return ApprovalRegistry(_Db())


def test_pending_ticket_cannot_be_consumed_without_an_approver():
    """The core fix: a self-issued ticket is NOT a self-approval."""
    registry = _registry()
    token = asyncio.run(
        registry.issue(action_id="a1", tenant_id="t1", user_id="u1", tool="browser")
    )
    # Requester re-enters before any approver acted -> refused.
    assert asyncio.run(registry.consume(action_id="a1", token=token, actor="u1")) is False


def test_approver_then_requester_round_trip():
    registry = _registry()
    token = asyncio.run(
        registry.issue(action_id="a2", tenant_id="t1", user_id="u1", tool="browser")
    )
    # A human approver approves it ...
    assert asyncio.run(
        registry.decide(action_id="a2", token=token, approved=True, actor="manager")
    ) is True
    # ... and only then can the requester consume it (once).
    assert asyncio.run(registry.consume(action_id="a2", token=token, actor="u1")) is True
    assert asyncio.run(registry.consume(action_id="a2", token=token, actor="u1")) is False


def test_denied_ticket_is_not_consumable():
    registry = _registry()
    token = asyncio.run(
        registry.issue(action_id="a3", tenant_id="t1", user_id="u1", tool="browser")
    )
    assert asyncio.run(
        registry.decide(action_id="a3", token=token, approved=False, actor="manager")
    ) is True
    assert asyncio.run(registry.consume(action_id="a3", token=token, actor="u1")) is False


def test_expired_ticket_cannot_be_approved():
    registry = _registry()
    token = asyncio.run(
        registry.issue(action_id="a4", tenant_id="t1", user_id="u1", tool="browser")
    )
    # Force expiry.
    registry._db["gate_approvals"].rows[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert asyncio.run(
        registry.decide(action_id="a4", token=token, approved=True, actor="manager")
    ) is False


def test_approval_layer_resume_requires_an_approved_ticket():
    """End-to-end through the layer: pending token -> deny; approved token -> allow."""
    from app.governance.gatekeeper import GateContext, GateDecision

    registry = _registry()
    layer = ApprovalLayer(registry=registry)
    token = asyncio.run(
        registry.issue(action_id="s1", tenant_id="t1", user_id="u1", tool="browser")
    )

    ctx = GateContext(
        tool="browser",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        annotations={"approval_token": token, "approval_action_id": "s1"},
    )
    verdict = asyncio.run(layer.evaluate(ctx))
    assert verdict.decision is GateDecision.DENY  # not approved yet

    assert asyncio.run(
        registry.decide(action_id="s1", token=token, approved=True, actor="manager")
    ) is True
    ctx2 = GateContext(
        tool="browser",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        annotations={"approval_token": token, "approval_action_id": "s1"},
    )
    verdict2 = asyncio.run(layer.evaluate(ctx2))
    assert verdict2.decision is GateDecision.ALLOW
