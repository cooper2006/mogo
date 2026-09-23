"""Integration tests for the six-layer gate chain (feature 001, US1/T013).

These tests exercise the orchestration and short-circuit semantics of
``Gatekeeper.evaluate`` with in-memory fake layers, so they need no MongoDB.
"""

from __future__ import annotations

import pytest

from app.governance.config import GateConfig
from app.governance.gatekeeper import (
    GateContext,
    GateDecision,
    Gatekeeper,
    GateVerdict,
)


class _FakeLayer:
    def __init__(self, name: str, decision: GateDecision = GateDecision.ALLOW, reason: str = "") -> None:
        self.name = name
        self._decision = decision
        self._reason = reason
        self.calls = 0

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        self.calls += 1
        return GateVerdict(decision=self._decision, layer=self.name, reason=self._reason)


class _RecordingAuditLayer:
    name = "audit"

    def __init__(self) -> None:
        self.records: list[GateVerdict] = []

    async def evaluate(self, ctx: GateContext) -> GateVerdict:
        verdict = ctx.annotations.get("verdict")
        self.records.append(verdict)
        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="audited")


def _make_gatekeeper(layers: list, monkeypatch) -> Gatekeeper:
    import app.governance.layers as layers_module

    monkeypatch.setattr(layers_module, "build_layers", lambda config: layers)
    return Gatekeeper(GateConfig())


@pytest.mark.asyncio
async def test_all_layers_pass_returns_allow(monkeypatch) -> None:
    audit = _RecordingAuditLayer()
    layers = [_FakeLayer("identity"), _FakeLayer("rbac"), audit]
    gate = _make_gatekeeper(layers, monkeypatch)

    verdict = await gate.evaluate("crm", GateContext(tool="crm", tenant_id="t1", user_id="u1"))

    assert verdict.decision is GateDecision.ALLOW
    assert audit.records and audit.records[-1].decision is GateDecision.ALLOW


@pytest.mark.asyncio
async def test_rbac_deny_short_circuits_before_later_layers(monkeypatch) -> None:
    audit = _RecordingAuditLayer()
    quota = _FakeLayer("quota")
    layers = [_FakeLayer("identity"), _FakeLayer("rbac", GateDecision.DENY, "no code"), quota, audit]
    gate = _make_gatekeeper(layers, monkeypatch)

    verdict = await gate.evaluate("crm", GateContext(tool="crm", tenant_id="t1", user_id="u1"))

    assert verdict.decision is GateDecision.DENY
    assert verdict.layer == "rbac"
    assert quota.calls == 0, "layers after the rejection must not run"
    assert audit.records and audit.records[-1].decision is GateDecision.DENY


@pytest.mark.asyncio
async def test_denial_status_code_maps_by_layer() -> None:
    assert GateVerdict(decision=GateDecision.DENY, layer="rbac").status_code == 403
    assert GateVerdict(decision=GateDecision.DENY, layer="approval").status_code == 409
    assert GateVerdict(decision=GateDecision.DENY, layer="quota").status_code == 429


@pytest.mark.asyncio
async def test_audit_always_runs_even_without_rejection(monkeypatch) -> None:
    audit = _RecordingAuditLayer()
    layers = [_FakeLayer("identity"), _FakeLayer("rbac"), audit]
    gate = _make_gatekeeper(layers, monkeypatch)

    await gate.evaluate("crm", GateContext(tool="crm", tenant_id="t1", user_id="u1"))

    assert len(audit.records) == 1
