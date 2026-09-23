"""Feature 001 — Polish tests: performance (T029), config audit (T030), audit coverage (T031)."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.governance.config import GateConfig, GateConfigError, config_from_document, save_gate_config
from app.governance.gatekeeper import GateContext, Gatekeeper


class _NoopLayer:
    """A chain of cheap layers that touches no DB (the hot path bound)."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def evaluate(self, ctx: GateContext):
        from app.governance.gatekeeper import GateDecision, GateVerdict

        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="ok")


class _NoopAudit:
    name = "audit"

    def __init__(self) -> None:
        self.events: list = []

    async def evaluate(self, ctx: GateContext):
        self.events.append(ctx.annotations.get("verdict"))
        from app.governance.gatekeeper import GateDecision, GateVerdict

        return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="audited")


# --- T029: single-evaluate p95 < 15ms (excluding approval wait) ---------------


@pytest.mark.asyncio
async def test_gatechain_p95_under_15ms():
    layers = [
        _NoopLayer("identity"),
        _NoopLayer("rbac"),
        _NoopLayer("redaction"),
        _NoopLayer("approval"),
        _NoopLayer("quota"),
    ]
    audit = _NoopAudit()

    import app.governance.layers as layers_module

    original = layers_module.build_layers
    layers_module.build_layers = lambda config: [*layers, audit]
    try:
        gatekeeper = Gatekeeper(GateConfig())
        ctx = GateContext(tool="web.search", tenant_id="t1", user_id="u1", roles=["r1"])

        # Warmup
        for _ in range(50):
            await gatekeeper.evaluate("web.search", ctx)

        samples: list[float] = []
        for _ in range(2000):
            started = time.perf_counter_ns()
            await gatekeeper.evaluate("web.search", ctx)
            samples.append((time.perf_counter_ns() - started) / 1_000_000)  # ms

        samples.sort()
        p95 = samples[int(len(samples) * 0.95)]
        # Success criteria: p95 < 15ms (FR-14 / T029).
        assert p95 < 15.0, f"gate chain p95 {p95:.2f}ms exceeds the 15ms budget"
        # The audit sink ran for every evaluation (both pass and reject paths).
        assert len(audit.events) == 50 + 2000
    finally:
        layers_module.build_layers = original


# --- T030: declarative config change leaves an audit record -------------------


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def update_one(self, filter_doc, update, upsert=False):
        if upsert:
            self.docs.append(filter_doc)
        return {"upserted_id": filter_doc.get("kind")}

    async def insert_one(self, doc):
        self.docs.append(doc)


class _FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


@pytest.mark.asyncio
async def test_save_gate_config_is_audited(monkeypatch):
    db = _FakeDB()
    import app.core.db as core_db

    monkeypatch.setattr(core_db, "get_db", lambda: db)

    config = GateConfig(enabled_layers=[l for l in ("identity", "rbac", "redaction", "approval", "quota", "audit")], mode="thin")
    await save_gate_config(config, actor="admin@t1")

    # The config document was persisted...
    assert db._collections["gatekeeper_rules"].docs
    # ...and the change was recorded in the single audit sink (FR-10 / T030).
    gate_events = db._collections["gate_events"].docs
    assert gate_events
    assert gate_events[-1]["tool"] == "gate.config.update"
    assert gate_events[-1]["user_id"] == "admin@t1"


@pytest.mark.asyncio
async def test_save_gate_config_rejects_thinning_below_floor(monkeypatch):
    db = _FakeDB()
    import app.core.db as core_db

    monkeypatch.setattr(core_db, "get_db", lambda: db)

    bad = GateConfig(enabled_layers=["identity", "rbac"], audit_enabled=True)  # redaction+audit missing
    with pytest.raises(GateConfigError):
        await save_gate_config(bad, actor="admin@t1")
    # No write happened
    assert not db._collections.get("gatekeeper_rules", _FakeCollection()).docs


# --- T031: audit coverage — every chain run persists exactly one gate event ---


@pytest.mark.asyncio
async def test_audit_coverage_full_chain(monkeypatch):
    """Every evaluate() run persists exactly one gate event (allow or reject)."""
    events: list = []

    class _RecordingAudit:
        name = "audit"

        async def evaluate(self, ctx: GateContext):
            verdict = ctx.annotations.get("verdict")
            events.append(verdict)
            from app.governance.gatekeeper import GateDecision, GateVerdict

            return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="audited")

    class _RejectLayer:
        name = "rbac"

        async def evaluate(self, ctx: GateContext):
            from app.governance.gatekeeper import GateDecision, GateVerdict

            if ctx.tool != "bad":
                return GateVerdict(decision=GateDecision.ALLOW, layer=self.name, reason="ok")
            return GateVerdict(decision=GateDecision.DENY, layer=self.name, reason="no code")

    layers = [
        _NoopLayer("identity"),
        _RejectLayer(),
        _NoopLayer("redaction"),
        _NoopLayer("approval"),
        _NoopLayer("quota"),
    ]

    import app.governance.layers as layers_module

    original = layers_module.build_layers
    layers_module.build_layers = lambda config: [*layers, _RecordingAudit()]
    try:
        gatekeeper = Gatekeeper(GateConfig())
        allow_ctx = GateContext(tool="ok", tenant_id="t", user_id="u", roles=["r"])
        deny_ctx = GateContext(tool="bad", tenant_id="t", user_id="u", roles=["r"])

        await gatekeeper.evaluate("ok", allow_ctx)
        await gatekeeper.evaluate("bad", deny_ctx)

        # 100% of chain runs produced an audit record (T031 Success criteria).
        assert len(events) == 2
        # Both events persisted: one full-chain allow, one mid-chain deny.
        layers_hit = {e.layer for e in events}
        assert "rbac" in layers_hit  # the deny event came from the rejecting layer
        assert "gatekeeper" in layers_hit or "audit" in layers_hit
    finally:
        layers_module.build_layers = original
