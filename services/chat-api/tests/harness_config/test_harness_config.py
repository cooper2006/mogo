"""Tests for harness elastic config core (feature 019): layers / floor / profile."""

from __future__ import annotations

import pytest

from app.harness_config.floor import (
    MIN_AUDIT_FIELDS,
    FloorViolation,
    assert_floor_intact,
    audit_covers_floor,
    minimal_audit_record,
    r4_always_denied,
)
from app.harness_config.layer_switch import (
    CANONICAL_LAYERS,
    DROPPABLE_LAYERS,
    REQUIRED_LAYERS,
    is_thin,
    resolve_layers,
)
from app.harness_config.profile import HarnessProfile, ProfileResolver


# --- layer switch (US1) ------------------------------------------------------

def test_thick_mode_enables_all_six_layers() -> None:
    assert resolve_layers("thick") == list(CANONICAL_LAYERS)


def test_thin_mode_drops_only_approval_and_quota() -> None:
    layers = resolve_layers("thin")
    assert "approval" not in layers
    assert "quota" not in layers
    for required in REQUIRED_LAYERS:
        assert required in layers


def test_droppable_is_exactly_approval_and_quota() -> None:
    assert DROPPABLE_LAYERS == {"approval", "quota"}


def test_explicit_enabled_list_still_ordered_canonically() -> None:
    layers = resolve_layers("thick", enabled=["audit", "rbac", "identity"])
    assert layers == ["identity", "rbac", "audit"]


def test_is_thin() -> None:
    assert is_thin("thin")
    assert not is_thin("thick")


# --- floor guard (US1/US3) ---------------------------------------------------

def test_floor_rejects_dropping_required_layer() -> None:
    with pytest.raises(FloorViolation):
        assert_floor_intact(enabled_layers=["identity", "approval", "quota", "audit"])


def test_floor_rejects_disabling_audit() -> None:
    with pytest.raises(FloorViolation):
        assert_floor_intact(enabled_layers=list(CANONICAL_LAYERS), audit_enabled=False)


def test_floor_allows_thin_mode() -> None:
    assert_floor_intact(enabled_layers=resolve_layers("thin"))


def test_r4_denied_in_every_mode() -> None:
    assert r4_always_denied("thick")
    assert r4_always_denied("thin")


def test_minimal_audit_record_has_four_fields() -> None:
    record = minimal_audit_record(subject="u1", tool="crm", result="denied", timestamp="2026-07-08T00:00:00Z")
    assert set(record) == set(MIN_AUDIT_FIELDS)


def test_audit_covers_floor_detects_missing_fields() -> None:
    assert audit_covers_floor(minimal_audit_record(subject="u1", tool="crm", result="ok", timestamp="t"))
    assert not audit_covers_floor({"subject": "u1", "tool": "crm"})


# --- profile resolution (US2) ------------------------------------------------

def test_default_is_thick() -> None:
    resolver = ProfileResolver()
    profile = resolver.resolve(scene="", tenant="", tool="")
    assert profile.mode == "thick"
    assert profile.resolved_layers() == list(CANONICAL_LAYERS)


def test_scene_beats_tenant_and_tool() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tenant", key="t1", mode="thin"))
    resolver.add(HarnessProfile(scope="scene", key="quick-ask", mode="thick"))
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))

    profile = resolver.resolve(scene="quick-ask", tenant="t1", tool="crm")
    assert profile.scope == "scene"
    assert profile.mode == "thick"


def test_tenant_beats_tool_when_no_scene() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tenant", key="t1", mode="thin"))
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thick"))

    profile = resolver.resolve(scene="", tenant="t1", tool="crm")
    assert profile.scope == "tenant"
    assert profile.mode == "thin"


def test_tool_profile_applies_when_no_scene_or_tenant() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))
    assert resolver.resolve(scene="x", tenant="y", tool="crm").mode == "thin"


def test_effective_layers_switch_per_call() -> None:
    resolver = ProfileResolver()
    resolver.add(HarnessProfile(scope="tool", key="crm", mode="thin"))

    thin = resolver.effective_layers(scene="", tenant="", tool="crm")
    thick = resolver.effective_layers(scene="", tenant="", tool="other")
    assert "approval" not in thin
    assert "approval" in thick


def test_profile_validation_rejects_illegal_thinning() -> None:
    with pytest.raises(FloorViolation):
        HarnessProfile(
            scope="tenant",
            key="t1",
            mode="thin",
            enabled_layers=["approval", "quota"],  # drops required layers
        ).validate()


def test_thin_audit_granularity_is_minimal() -> None:
    assert HarnessProfile(mode="thin").resolved_audit_granularity() == "minimal"
    assert HarnessProfile(mode="thick").resolved_audit_granularity() == "full"


# --- gate adapter (T014) -----------------------------------------------------

def test_plan_thick_uses_all_layers_and_gatekeeper() -> None:
    from app.harness_config.gate_adapter import GATEKEEPER_READY, build_gate_plan

    plan = build_gate_plan(mode="thick", backend=GATEKEEPER_READY)
    assert plan.layers == list(CANONICAL_LAYERS)
    assert plan.skipped_layers == []
    assert plan.backend == GATEKEEPER_READY


def test_plan_thin_skips_approval_and_quota_keeps_audit() -> None:
    from app.harness_config.gate_adapter import build_gate_plan

    plan = build_gate_plan(mode="thin")
    assert set(plan.skipped_layers) == {"approval", "quota"}
    assert plan.audit_enabled() is True
    assert plan.audit_granularity == "minimal"


def test_plan_rejects_floor_breach() -> None:
    from app.harness_config.gate_adapter import build_gate_plan
    from app.harness_config.floor import FloorViolation
    import pytest as _pytest

    with _pytest.raises(FloorViolation):
        build_gate_plan(mode="thin", enabled_layers=["approval", "quota"])


def test_plan_rejects_unknown_backend() -> None:
    from app.harness_config.gate_adapter import GateAdapterError, build_gate_plan
    import pytest as _pytest

    with _pytest.raises(GateAdapterError):
        build_gate_plan(mode="thick", backend="magic")


def test_backend_transition_until_gatekeeper_ready() -> None:
    from app.harness_config.gate_adapter import (
        GATEKEEPER_READY,
        TRANSITION,
        backend_for,
    )

    assert backend_for(False) == TRANSITION
    assert backend_for(True) == GATEKEEPER_READY


def test_describe_plan_is_serializable() -> None:
    from app.harness_config.gate_adapter import build_gate_plan, describe_plan

    payload = describe_plan(build_gate_plan(mode="thin"))
    assert payload["mode"] == "thin"
    assert payload["auditEnabled"] is True
    assert "approval" in payload["skippedLayers"]


def test_required_layers_never_skipped() -> None:
    from app.harness_config.gate_adapter import build_gate_plan

    plan = build_gate_plan(mode="thin")
    for required in REQUIRED_LAYERS:
        assert required not in plan.skipped_layers


# --- 019 FR-7 / FR-9: CRUD endpoint ------------------------------------------


class _FakeColl:
    """Minimal in-memory Motor-compatible fake for the harness_profiles collection."""

    def __init__(self, rows: list[dict] | None = None):
        self._rows: list[dict] = [dict(r) for r in (rows or [])]

    def find(self, query):
        query = {k: v for k, v in query.items() if v is not None and k != "main_id"}
        rows = [r for r in self._rows]
        for k, v in query.items():
            rows = [r for r in rows if r.get(k) == v]
        class _Cur:
            def __init__(self, rows):
                self._rows = rows
            async def to_list(self, length=None):
                return self._rows[:length] if length else self._rows
        return _Cur(rows)

    async def find_one(self, query):
        query = {k: v for k, v in query.items() if v is not None and k != "main_id"}
        for row in self._rows:
            if all(row.get(k) == v for k, v in query.items()):
                return dict(row)
        return None

    async def replace_one(self, query, doc, upsert=False):
        query = {k: v for k, v in query.items() if v is not None and k != "main_id"}
        for i, row in enumerate(self._rows):
            if all(row.get(k) == v for k, v in query.items()):
                self._rows[i] = dict(doc)
                return type("R", (), {})()
        if upsert:
            self._rows.append(dict(doc))
        return type("R", (), {})()

    async def delete_one(self, query):
        query = {k: v for k, v in query.items() if v is not None and k != "main_id"}
        for i, row in enumerate(self._rows):
            if all(row.get(k) == v for k, v in query.items()):
                del self._rows[i]
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()


class _FakeDB:
    def __init__(self, rows: list[dict] | None = None):
        self._coll = _FakeColl(rows)
    def __getitem__(self, name):
        assert name == "harness_profiles"
        return self._coll


def _fake_resolve(monkeypatch, *, main_id="main-test", user_id="u-1", role="full_access_admin"):
    """Patch the session-user resolver so the endpoint doesn't hit the DB."""
    import app.services.end_user_session as _s

    async def _resolve(authorization=None):
        return {"main_id": main_id, "user": {"_id": user_id}, "user_id": user_id, "role": role}

    monkeypatch.setattr(_s, "resolve_session_user", _resolve)


def _fake_full_access(monkeypatch, allowed=True):
    import app.api.endpoints.dsh_session_versioning as _sv

    async def _fake(db, main_id, user_id):
        return allowed

    monkeypatch.setattr(_sv, "_user_has_full_access", _fake)


def test_upsert_profile_creates_and_audits(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp

    _fake_resolve(monkeypatch)
    _fake_full_access(monkeypatch, allowed=True)
    db = _FakeDB([])
    monkeypatch.setattr(hp, "get_db", lambda: db)

    result = asyncio.run(hp.upsert_profile(
        "scene", "research",
        {"mode": "thin"},
        authorization="Bearer x",
    ))
    assert result["code"] == 0
    assert result["data"]["mode"] == "thin"
    assert len(db._coll._rows) == 1
    assert db._coll._rows[0]["scope"] == "scene"


def test_upsert_profile_rejects_floor_violation(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp

    _fake_resolve(monkeypatch)
    _fake_full_access(monkeypatch, allowed=True)
    db = _FakeDB([])
    monkeypatch.setattr(hp, "get_db", lambda: db)

    # Dropping a required layer (identity) must be rejected server-side (FR-8).
    import pytest
    with pytest.raises(Exception, match="floor violation|400"):
        asyncio.run(hp.upsert_profile(
            "scene", "s",
            {"mode": "thick", "enabled_layers": ["rbac", "audit"]},
            authorization="Bearer x",
        ))
    assert len(db._coll._rows) == 0  # nothing was persisted


def test_upsert_profile_requires_full_access(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp
    from fastapi import HTTPException

    _fake_resolve(monkeypatch)
    _fake_full_access(monkeypatch, allowed=False)
    db = _FakeDB([])
    monkeypatch.setattr(hp, "get_db", lambda: db)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(hp.upsert_profile(
            "scene", "s", {"mode": "thick"}, authorization="Bearer x",
        ))
    assert exc.value.status_code == 403
    assert "FR-9" in exc.value.detail


def test_delete_profile_removes_and_audits(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp

    _fake_resolve(monkeypatch)
    _fake_full_access(monkeypatch, allowed=True)
    existing = {"scope": "scene", "key": "s1", "mode": "thick", "tenant_id": "main-test"}
    db = _FakeDB([existing])
    monkeypatch.setattr(hp, "get_db", lambda: db)

    result = asyncio.run(hp.delete_profile("scene", "s1", authorization="Bearer x"))
    assert result["code"] == 0
    assert len(db._coll._rows) == 0


def test_delete_profile_not_found(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp
    from fastapi import HTTPException

    _fake_resolve(monkeypatch)
    _fake_full_access(monkeypatch, allowed=True)
    db = _FakeDB([])
    monkeypatch.setattr(hp, "get_db", lambda: db)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(hp.delete_profile("scene", "missing", authorization="Bearer x"))
    assert exc.value.status_code == 404


def test_list_profiles_returns_all(monkeypatch):
    import asyncio
    import app.api.endpoints.harness_profiles as hp

    _fake_resolve(monkeypatch)
    rows = [
        {"scope": "scene", "key": "a", "mode": "thick", "tenant_id": "main-test"},
        {"scope": "scene", "key": "b", "mode": "thin", "tenant_id": "main-test"},
    ]
    db = _FakeDB(rows)
    monkeypatch.setattr(hp, "get_db", lambda: db)

    result = asyncio.run(hp.list_profiles(authorization="Bearer x"))
    assert result["data"]["total"] == 2
