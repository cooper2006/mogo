"""036 trust-rating (L1-L4): pure policy, persistence, gate cap, dual-approver, scanner.

No asyncio pytest mode is configured, so every coroutine is driven via
``asyncio.run``. Upstream 032/016 collections are stubbed with an in-memory DB.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from app.governance.gatekeeper import GateContext
from app.governance.layers.approval import ApprovalLayer, ApprovalRegistry
from app.services.eval_gate import RUNS_COLLECTION
from app.services.skill_market.quality_metrics import QUALITY_METRICS_COLLECTION
from app.system_audit.constants import SYSTEM_AUDIT_COLLECTION
from app.services.trust_rating.ratings import (
    CAPS_COLLECTION,
    DEFAULT_DOWNGRADE_WINDOW_DAYS,
    RATINGS_COLLECTION,
    SCAN_STATE_COLLECTION,
    SETTINGS_COLLECTION,
    TRUST_TO_AUTONOMY_CAP,
    apply_trust_cap,
    ensure_rating,
    get_downgrade_settings,
    get_rating,
    list_ratings,
    next_downgrade_action,
    rating_distribution,
    recompute_rating,
    record_change,
    required_approvals_for,
    trust_caps_for_tenant,
)
from app.services.trust_rating.downgrade_scanner import run_downgrade_scan

TODAY = date(2026, 10, 23)


# --- in-memory MongoDB -----------------------------------------------------

def _dig(doc, dotted):
    cur = doc
    for part in str(dotted).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(row, flt):
    for key, value in (flt or {}).items():
        if key == "$or":
            if not any(_matches(row, branch) for branch in value):
                return False
            continue
        actual = _dig(row, key)
        if isinstance(value, dict) and set(value).issubset({"$in", "$gt", "$gte", "$lt", "$lte", "$ne"}):
            if "$in" in value and actual not in value["$in"]:
                return False
            if "$gt" in value and not (actual is not None and actual > value["$gt"]):
                return False
            if "$gte" in value:
                if actual is None:
                    return False
                if isinstance(actual, str) != isinstance(value["$gte"], str):
                    return False
                if actual < value["$gte"]:
                    return False
            if "$lt" in value and not (actual is not None and actual < value["$lt"]):
                return False
            if "$lte" in value:
                if actual is None:
                    return False
                if isinstance(actual, str) != isinstance(value["$lte"], str):
                    return False
                if actual > value["$lte"]:
                    return False
            if "$ne" in value and actual == value["$ne"]:
                return False
            continue
        if actual != value:
            return False
    return True


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key, direction=1):
        self._rows = sorted(self._rows, key=lambda r: r.get(key) or 0, reverse=int(direction) < 0)
        return self

    def limit(self, count):
        self._rows = list(self._rows)[: int(count)]
        return self

    async def to_list(self, length=0):
        return list(self._rows)


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, flt, projection=None):
        return _Result([r for r in self.rows if _matches(r, flt)])

    async def find_one(self, flt, projection=None):
        for r in self.rows:
            if _matches(r, flt):
                return r
        return None

    def aggregate(self, pipeline):
        return _Result(list(self.rows))

    async def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = uuid.uuid4().hex
        self.rows.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, flt, update, upsert=False):
        for r in self.rows:
            if _matches(r, flt):
                _apply(r, update)
                return type("R", (), {"modified_count": 1, "upserted_id": None})()
        if upsert:
            new = {k: v for k, v in (flt or {}).items() if not k.startswith("$")}
            new["_id"] = new.get("_id") or uuid.uuid4().hex
            self.rows.append(new)
            _apply(new, update)
            return type("R", (), {"modified_count": 0, "upserted_id": new["_id"]})()
        return type("R", (), {"modified_count": 0, "upserted_id": None})()

    async def create_index(self, keys, **kwargs):
        return None


def _apply(doc, update):
    for op, fields in update.items():
        if op == "$set":
            doc.update(fields)
        elif op == "$inc":
            for k, v in fields.items():
                doc[k] = int(doc.get(k) or 0) + int(v)
        elif op == "$setOnInsert":
            for k, v in fields.items():
                doc.setdefault(k, v)
        elif op == "$push":
            for k, v in fields.items():
                doc.setdefault(k, []).append(v)


class MemoryDb:
    def __init__(self):
        self.data = {}

    def __getitem__(self, name):
        if name not in self.data:
            self.data[name] = []
        return _Collection(self.data[name])

    def rows(self, name):
        return self.data.setdefault(name, [])


def _seed_032(db, tenant, skill, passing, count, start=TODAY):
    for offset in range(count):
        db.rows(RUNS_COLLECTION).append(
            {
                "tenant_id": tenant,
                "skill_id": skill,
                "passed": passing,
                "created_at": datetime.combine(start - timedelta(days=offset), datetime.min.time(), tzinfo=timezone.utc),
            }
        )


def _seed_016(db, tenant, skill, score_ok=True):
    db.rows(QUALITY_METRICS_COLLECTION).append(
        {
            "tenant_id": tenant,
            "skill_key": skill,
            "date": TODAY.isoformat(),
            "total_calls": 50,
            "successful_calls": 45 if score_ok else 5,
            "adopted_calls": 40 if score_ok else 5,
            "corrected_calls": 3 if score_ok else 40,
            "success_tracked": True,
        }
    )


def _audit_rows(db):
    return db.rows(SYSTEM_AUDIT_COLLECTION)


def run(coro):
    return asyncio.run(coro)


# --- pure policy -----------------------------------------------------------

def test_apply_trust_cap_caps_autonomy():
    assert apply_trust_cap("L5", "L2") == "L2"
    assert apply_trust_cap("L4", "L4") == "L4"
    assert apply_trust_cap("L5", "L4") == "L5"
    # 无评级 -> L1 (fail-closed)
    assert apply_trust_cap("L5", None) == "L1"
    assert apply_trust_cap("L5", "L9") == "L1"
    # 租户覆盖
    caps = {**TRUST_TO_AUTONOMY_CAP, "L2": "L4"}
    assert apply_trust_cap("L5", "L2", caps) == "L4"


def test_tenant_caps_override_filters_invalid():
    db = MemoryDb()
    db.rows(CAPS_COLLECTION).append({"_id": "t1", "caps": {"L2": "L4", "L3": "L9"}})
    caps = run(trust_caps_for_tenant(db, "t1"))
    assert caps["L2"] == "L4"
    assert caps["L3"] == "L3"  # invalid override dropped


def test_required_approvals_l4_r2_only():
    assert required_approvals_for("L4", "R2") == 2
    assert required_approvals_for("L4", "R3") == 2
    assert required_approvals_for("L4", "R1") == 1
    assert required_approvals_for("L3", "R3") == 1
    assert required_approvals_for("L5", "R2") == 1


def test_next_downgrade_action_downgrade_deprecate_reset():
    d = next_downgrade_action(level="L2", passing=False, below_since="2026-10-03", now=TODAY, window_days=21)
    assert d["action"] == "downgrade" and d["target_level"] == "L1"
    d = next_downgrade_action(level="L1", passing=False, below_since="2026-10-03", now=TODAY, window_days=21)
    assert d["action"] == "deprecate"
    d = next_downgrade_action(level="L4", passing=False, below_since="2026-10-22", now=TODAY, window_days=21)
    assert d["action"] == "none" and d["below_streak_days"] == 2
    d = next_downgrade_action(level="L3", passing=True, below_since="2026-10-01", now=TODAY, window_days=21)
    assert d["action"] == "reset_streak" and d["below_since"] is None


# --- persistence -----------------------------------------------------------

def test_new_skill_rating_defaults_to_l1():
    db = MemoryDb()
    doc = run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="alice"))
    assert doc["level"] == "L1"
    assert doc["asset_type"] == "skill" and doc["asset_key"] == "s1"
    events = [r for r in _audit_rows(db) if r.get("action") == "trust.create"]
    assert len(events) == 1


def test_record_change_promote_audits_before_after():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="alice"))
    updated = run(
        record_change(
            db,
            tenant_id="t1",
            asset_type="skill",
            asset_key="s1",
            target_level="L2",
            reason="manual_promote",
            actor="alice",
        )
    )
    assert updated["level"] == "L2"
    assert updated["previous_level"] == "L1"
    event = [r for r in _audit_rows(db) if r.get("action") == "trust.change"][0]
    assert event["before"]["level"] == "L1"
    assert event["after"]["level"] == "L2"
    assert event["actor"] == "alice"


def test_promote_to_l3_requires_quality_evidence():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="alice"))
    run(record_change(db, tenant_id="t1", asset_type="skill", asset_key="s1", target_level="L2", reason="manual_promote", actor="alice"))
    try:
        run(
            record_change(
                db,
                tenant_id="t1",
                asset_type="skill",
                asset_key="s1",
                target_level="L3",
                reason="manual_promote",
                actor="alice",
            )
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
    # 带质量证据可通过
    ok = run(
        record_change(
            db,
            tenant_id="t1",
            asset_type="skill",
            asset_key="s1",
            target_level="L3",
            reason="manual_promote",
            actor="alice",
            evidence={"source": "032", "quality_passed": True, "pass_rate": 0.9},
        )
    )
    assert ok["level"] == "L3"


def test_record_change_rejects_multi_step_hop():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="alice"))
    try:
        run(record_change(db, tenant_id="t1", asset_type="skill", asset_key="s1", target_level="L4", reason="manual_promote", actor="alice"))
        raised = False
    except ValueError:
        raised = True
    assert raised


# --- gate: FR-8 cap + FR-9 dual approver -----------------------------------

def test_gate_caps_autonomy_by_trust_level():
    db = MemoryDb()
    registry = ApprovalRegistry(db=db)
    layer = ApprovalLayer(registry=registry)
    # L4 x R2 = require_approval; L2 x R2 = allow (see schema.AUTONOMY_MATRIX).
    ctx = GateContext(tool="t", autonomy_level="L4", risk_level="R2", annotations={"trust_level": "L2"})
    verdict = run(layer.evaluate(ctx))
    assert verdict.allowed, verdict.reason


def test_gate_without_trust_annotation_keeps_001_behaviour():
    db = MemoryDb()
    registry = ApprovalRegistry(db=db)
    layer = ApprovalLayer(registry=registry)
    ctx = GateContext(tool="t", autonomy_level="L4", risk_level="R2", annotations={})
    verdict = run(layer.evaluate(ctx))
    assert verdict.decision.value == "require_approval"


def test_l4_r2_ticket_needs_two_approvers():
    db = MemoryDb()
    registry = ApprovalRegistry(db=db)
    token = run(
        registry.issue(
            action_id="a1",
            tenant_id="t1",
            user_id="u1",
            tool="tool",
            risk_level="R2",
            autonomy_level="L4",
            required_approvals=2,
            trust_level="L4",
        )
    )
    # 第一人批准后仍未满额，requester 不能 consume。
    assert run(registry.decide(action_id="a1", token=token, approved=True, actor="approverA")) is True
    assert run(registry.consume(action_id="a1", token=token, actor="u1")) is False
    # 同一人不能重复批准。
    assert run(registry.decide(action_id="a1", token=token, approved=True, actor="approverA")) is False
    # 第二人批准后满额，可以 consume。
    assert run(registry.decide(action_id="a1", token=token, approved=True, actor="approverB")) is True
    assert run(registry.consume(action_id="a1", token=token, actor="u1")) is True
    # 已消费不可复用。
    assert run(registry.consume(action_id="a1", token=token, actor="u1")) is False


def test_l4_r2_single_approver_cannot_consume():
    db = MemoryDb()
    registry = ApprovalRegistry(db=db)
    token = run(
        registry.issue(
            action_id="a2",
            tenant_id="t1",
            user_id="u1",
            tool="tool",
            risk_level="R2",
            autonomy_level="L4",
            required_approvals=2,
        )
    )
    run(registry.decide(action_id="a2", token=token, approved=True, actor="approverA"))
    assert run(registry.consume(action_id="a2", token=token, actor="u1")) is False


# --- downgrade scanner (FR-10 / FR-11) -------------------------------------

def test_21_day_downgrade_drops_level_and_resets_streak():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update(
        {"level": "L2", "below_since": (TODAY - timedelta(days=DEFAULT_DOWNGRADE_WINDOW_DAYS - 1)).isoformat(), "below_streak_days": 0}
    )
    _seed_032(db, "t1", "s1", passing=False, count=25)
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["action"] == "downgrade"
    assert result["rating"]["level"] == "L1"
    assert result["rating"]["below_streak_days"] == 0
    assert result["signal"]["source"] == "032"
    event = [r for r in _audit_rows(db) if r.get("reason") == "auto_downgrade"]
    assert event and event[-1]["before"]["level"] == "L2" and event[-1]["after"]["level"] == "L1"


def test_downgrade_switch_closed_triggers_nothing():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    doc = db.rows(RATINGS_COLLECTION)[0]
    doc.update({"level": "L2", "below_since": (TODAY - timedelta(days=40)).isoformat()})
    db.rows(SETTINGS_COLLECTION).append({"_id": "t1", "enabled": False, "window_days": DEFAULT_DOWNGRADE_WINDOW_DAYS})
    _seed_032(db, "t1", "s1", passing=False, count=25)
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["rating"]["level"] == "L2"


def test_l1_still_failing_marks_deprecate_pending():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update(
        {"below_since": (TODAY - timedelta(days=DEFAULT_DOWNGRADE_WINDOW_DAYS - 1)).isoformat()}
    )
    _seed_032(db, "t1", "s1", passing=False, count=25)
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["action"] == "deprecate"
    assert result["rating"]["deprecate_pending"] is True
    assert [r for r in _audit_rows(db) if r.get("action") == "trust.deprecate_requested"]


def test_passing_signal_resets_streak():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update({"level": "L2", "below_since": (TODAY - timedelta(days=5)).isoformat(), "below_streak_days": 6})
    _seed_032(db, "t1", "s1", passing=True, count=25)
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["action"] == "reset_streak"
    assert result["rating"]["below_since"] is None


def test_insufficient_signal_is_lenient():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update({"level": "L2"})
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["signal"]["available"] is False
    assert result["rating"]["level"] == "L2"


def test_scanner_walks_ratings_and_records_state():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update(
        {"level": "L2", "below_since": (TODAY - timedelta(days=DEFAULT_DOWNGRADE_WINDOW_DAYS - 1)).isoformat()}
    )
    _seed_032(db, "t1", "s1", passing=False, count=25)
    run(run_downgrade_scan(db, tenant_id="t1"))
    assert run(get_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1"))["level"] == "L1"
    state = db.rows(SCAN_STATE_COLLECTION)[0]
    assert state["_id"] == "downgrade" and state["evaluated"] >= 1


def test_scanner_tolerates_orphan_ratings():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION).append(
        {"tenant_id": "t1", "asset_type": "nope", "asset_key": "x", "level": "L1"}
    )
    _seed_032(db, "t1", "s1", passing=True, count=25)
    evaluated = run(run_downgrade_scan(db, tenant_id="t1"))
    assert evaluated == 1  # 非法评级被跳过，不影响正常项


# --- API RBAC (FR-4, fail-closed) ------------------------------------------

def _build_client(user: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.trust_ratings import router
    from app.api.deps import get_current_admin_user as dep

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[dep] = lambda: user
    return app, TestClient(app)


def _patch_get_db(monkeypatch, db):
    import app.api.routes.trust_ratings as routes_module

    monkeypatch.setattr(routes_module, "get_db", lambda: db)


def _org_admin(tenant="t1"):
    return {"user_id": "u1", "username": "admin", "tenant_id": tenant, "role_name": "组织管理员"}


def _platform_admin(tenant="t1"):
    return {"user_id": "u9", "username": "platform", "tenant_id": tenant, "role_name": "平台管理员"}


def test_api_org_admin_reads_but_cannot_manage(monkeypatch):
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", owner_id="alice", created_by="alice"))
    _patch_get_db(monkeypatch, db)
    _, client = _build_client(_org_admin())
    assert client.get("/api/trust-ratings").status_code == 200
    assert client.get("/api/trust-ratings/settings").status_code == 200
    # 未持 trust:manage → 403 fail-closed。
    assert (
        client.post(
            "/api/trust-ratings/skill/s1/changes",
            json={"target_level": "L2", "reason": "manual_promote"},
        ).status_code
        == 403
    )
    assert client.put("/api/trust-ratings/settings", json={"window_days": 14}).status_code == 403


def test_api_platform_admin_can_change_rating(monkeypatch):
    db = MemoryDb()
    _patch_get_db(monkeypatch, db)
    _, client = _build_client(_platform_admin())
    resp = client.post(
        "/api/trust-ratings/skill/s1/changes",
        json={"target_level": "L2", "reason": "manual_promote", "owner_id": "alice"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["level"] == "L2"
    resp = client.put("/api/trust-ratings/settings", json={"window_days": 14})
    assert resp.status_code == 200
    assert resp.json()["data"]["window_days"] == 14
    assert client.get("/api/trust-ratings/distribution").json()["data"]["L2"] == 1


def test_api_unknown_role_cannot_manage(monkeypatch):
    db = MemoryDb()
    _patch_get_db(monkeypatch, db)
    _, client = _build_client({"user_id": "u1", "tenant_id": "t1", "role_name": "审核员"})
    # 只读是 baseline；未持 trust:manage 一律 403。
    assert client.get("/api/trust-ratings").status_code == 200
    assert (
        client.post(
            "/api/trust-ratings/skill/s1/changes",
            json={"target_level": "L2", "reason": "manual_promote"},
        ).status_code
        == 403
    )


# --- FR-14 / FR-16 ---------------------------------------------------------

def test_list_hides_l1_from_non_owner():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", owner_id="alice", created_by="alice"))
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s2", owner_id="bob", created_by="bob"))
    run(record_change(db, tenant_id="t1", asset_type="skill", asset_key="s2", target_level="L2", reason="manual_promote", actor="bob"))
    rows = run(list_ratings(db, tenant_id="t1", visible_to="alice"))
    keys = {r["asset_key"] for r in rows}
    assert "s1" in keys and "s2" in keys
    rows = run(list_ratings(db, tenant_id="t1", visible_to="mallory"))
    keys = {r["asset_key"] for r in rows}
    assert "s1" not in keys and "s2" in keys


def test_distribution_counts_by_level():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="a"))
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s2", created_by="b"))
    run(record_change(db, tenant_id="t1", asset_type="skill", asset_key="s2", target_level="L2", reason="manual_promote", actor="b"))
    counts = run(rating_distribution(db, tenant_id="t1"))
    assert counts["L1"] == 1 and counts["L2"] == 1


# --- 032/016 fallback ------------------------------------------------------

def test_quality_signal_uses_016_when_032_insufficient():
    db = MemoryDb()
    run(ensure_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", created_by="sys"))
    db.rows(RATINGS_COLLECTION)[0].update({"level": "L2", "below_since": (TODAY - timedelta(days=40)).isoformat()})
    _seed_016(db, "t1", "s1", score_ok=False)
    result = run(recompute_rating(db, tenant_id="t1", asset_type="skill", asset_key="s1", actor="alice", as_of=TODAY))
    assert result["signal"]["source"] == "016"
    assert result["rating"]["level"] == "L1"