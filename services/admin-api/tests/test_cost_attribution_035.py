"""035 US2/US3 (T023/T026/T028/T029): six-dimension cost attribution + cost drill-down.

The dashboard cost section must bucket cost by department / business line / agent /
space / user / enterprise, stay honest when a dimension has no data source, and
reconcile to the per-model total. The analytics endpoints must expose a
per-call ``costUsd`` that is consistent with the aggregated total.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _match(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, value in (query or {}).items():
        target = doc.get(key)
        if isinstance(value, dict) and any(str(k).startswith("$") for k in value):
            for op, operand in value.items():
                if op == "$in" and target not in operand:
                    return False
                if op == "$ne" and target == operand:
                    return False
                if op == "$gte" and (target is None or target < operand):
                    return False
                if op == "$lt" and (target is None or target >= operand):
                    return False
        else:
            if target != value:
                return False
    return True


class _Cursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, spec):
        return self

    def skip(self, n):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _Coll:
    def __init__(self, docs: list[dict[str, Any]] | None = None, aggregate_rows=None) -> None:
        self._docs = list(docs or [])
        self._aggregate_rows = list(aggregate_rows or [])

    def find(self, query=None, projection=None, *a, **k):
        matched = [d for d in self._docs if _match(d, query or {})]
        if projection:
            matched = [{p: d.get(p) for p in projection} for d in matched]
        return _Cursor(matched)

    async def find_one(self, query=None, *a, **k):
        for d in self._docs:
            if _match(d, query or {}):
                return d
        return None

    async def count_documents(self, query=None, *a, **k):
        return len([d for d in self._docs if _match(d, query or {})])

    async def distinct(self, field, query=None, *a, **k):
        seen = []
        for d in self._docs:
            if _match(d, query or {}) and d.get(field) not in seen:
                seen.append(d.get(field))
        return seen

    def aggregate(self, pipeline):
        return _Cursor(list(self._aggregate_rows))


class _DB:
    def __init__(self, **colls: dict[str, Any]) -> None:
        self._colls = colls

    def __getitem__(self, name: str):
        return self._colls.get(name, _Coll())

    def __getattr__(self, name: str):
        return self._colls.get(name, _Coll())


# PanWeiDB mode keeps `to_backend_id` string-based so plain _id values work with
# the in-memory fake match (ids calls `app.core.db.is_panweidb_backend` lazily).
def _use_panwei_ids(monkeypatch) -> None:
    import app.core.db as db

    monkeypatch.setattr(db, "is_panweidb_backend", lambda: True)


DEPT_ENG = "507f1f77bcf86cd799439011"
DEPT_HQ = "507f1f77bcf86cd799439012"
BLINE = "507f1f77bcf86cd799439013"


def _raw_rows(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        "tenant_id": "tenant-1",
        "user_id": "user-1001",
        "model_name": "gpt-5.2",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cost_estimate_usd": 0.0,
        "created_at": _now(),
    }
    return [{**base, **row} for row in rows]


def _aggregate_rows(*models: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"_id": m.get("model"), "calls": m.get("calls", 1), "prompt_tokens": m.get("prompt_tokens", 0), "completion_tokens": m.get("completion_tokens", 0)}
        for m in models
    ]


def _usage_coll(raw_rows, aggregate_rows):
    return _Coll(raw_rows, aggregate_rows=aggregate_rows)


def _cost_section(db, tenant_id="tenant-1"):
    import asyncio

    from app.api.routes.dashboard import _cost_section

    return asyncio.run(_cost_section(db, tenant_id))


# --------------------------------------------------------------------------
# T023: dashboard six-dimension attribution
# --------------------------------------------------------------------------

def test_cost_section_populates_all_six_dimensions(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    raw = _raw_rows(
        {"agent_id": "research.progressive", "skill_id": "v1", "workspace_id": "ws-42"},
        {"agent_id": "research.progressive", "skill_id": "v1", "workspace_id": "ws-42"},
        {"agent_id": "doc.synthesis", "workspace_id": ""},
    )
    usage = _usage_coll(raw, _aggregate_rows({"model": "gpt-5.2", "calls": 3, "prompt_tokens": 300, "completion_tokens": 150}))
    orgs = _Coll([
        {"_id": DEPT_ENG, "tenant_id": "tenant-1", "name": "工程部", "path_ids": [DEPT_HQ], "parent_id": DEPT_HQ},
        {"_id": DEPT_HQ, "tenant_id": "tenant-1", "name": "总部", "path_ids": [], "parent_id": None},
        {"_id": BLINE, "tenant_id": "tenant-1", "name": "云事业部", "path_ids": [], "parent_id": None, "is_business_line": True},
    ])
    rels = _Coll([
        {"tenant_id": "tenant-1", "user_id": "user-1001", "org_id": DEPT_ENG},
    ])
    db = _DB(
        token_usage_logs=usage,
        end_user_org_relations=rels,
        org_units=orgs,
    )
    section = _cost_section(db)

    assert section["reconciles"] is True
    agent = section["agentAttribution"]
    assert agent["available"] is True
    agent_keys = [i["key"] for i in agent["items"]]
    assert "research.progressive" in agent_keys
    assert "doc.synthesis" in agent_keys

    space = section["spaceAttribution"]
    assert space["available"] is True
    space_keys = [i["key"] for i in space["items"]]
    assert "ws-42" in space_keys
    # empty workspace falls into 未分配 (never fabricated into a real space).
    assert "未分配" in space_keys

    dept = section["departmentAttribution"]
    assert dept["available"] is True
    assert [i["key"] for i in dept["items"]] == ["工程部"]

    business_line = section["businessLineAttribution"]
    assert business_line["available"] is True
    # 工程部's chain has no is_business_line flag -> falls back to the root-side dept.
    assert [i["key"] for i in business_line["items"]] == ["总部"]

    user = section["userAttribution"]
    assert user["available"] is True
    assert [i["key"] for i in user["items"]] == ["user-1001"]

    enterprise = section["enterpriseAttribution"]
    assert enterprise["available"] is True
    assert [i["key"] for i in enterprise["items"]] == ["tenant-1"]


def test_business_line_uses_highest_is_business_line_ancestor(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    usage = _usage_coll(
        _raw_rows({}),
        _aggregate_rows({"model": "gpt-5.2", "calls": 1, "prompt_tokens": 100, "completion_tokens": 50}),
    )
    orgs = _Coll([
        {"_id": BLINE, "tenant_id": "tenant-1", "name": "云事业部", "path_ids": [], "parent_id": None, "is_business_line": True},
        {"_id": DEPT_HQ, "tenant_id": "tenant-1", "name": "总部", "path_ids": [BLINE], "parent_id": None},
        {"_id": DEPT_ENG, "tenant_id": "tenant-1", "name": "工程部", "path_ids": [BLINE, DEPT_HQ], "parent_id": DEPT_HQ},
    ])
    rels = _Coll([{"tenant_id": "tenant-1", "user_id": "user-1001", "org_id": DEPT_ENG}])
    section = _cost_section(_DB(token_usage_logs=usage, end_user_org_relations=rels, org_units=orgs))
    assert [i["key"] for i in section["businessLineAttribution"]["items"]] == ["云事业部"]


# --------------------------------------------------------------------------
# T028: honest placeholder when a dimension has no data source
# --------------------------------------------------------------------------

def test_cost_section_dimension_without_source_is_not_fabricated(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    raw = _raw_rows({}, {"workspace_id": ""})
    usage = _usage_coll(raw, _aggregate_rows({"model": "gpt-5.2", "calls": 2, "prompt_tokens": 200, "completion_tokens": 100}))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)

    # rows exist but carry no agent / space / department source.
    for key in ("agentAttribution", "spaceAttribution", "departmentAttribution", "businessLineAttribution"):
        attr = section[key]
        assert attr["available"] is False, key
        assert isinstance(attr["reason"], str) and attr["reason"], key
        assert [i["key"] for i in attr["items"]] == ["未分配"]
    # enterprise dimension always has a real value (the queried tenant).
    assert section["enterpriseAttribution"]["available"] is True
    assert section["reconciles"] is True


def test_cost_section_empty_tenant_all_dimensions_unavailable(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    db = _DB(token_usage_logs=_usage_coll([], []), end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db, tenant_id="empty-tenant")
    for key in (
        "departmentAttribution",
        "businessLineAttribution",
        "agentAttribution",
        "spaceAttribution",
        "userAttribution",
        "enterpriseAttribution",
    ):
        assert section[key]["available"] is False, key
        assert section[key]["items"] == []
    assert section["reconciles"] is True


# --------------------------------------------------------------------------
# T029: dimension buckets reconcile to the section total
# --------------------------------------------------------------------------

def test_attribution_buckets_reconcile_to_total_cost(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    raw = _raw_rows(
        {"agent_id": "a1"},
        {"agent_id": "a1"},
        {"agent_id": "a2"},
    )
    usage = _usage_coll(raw, _aggregate_rows({"model": "gpt-5.2", "calls": 3, "prompt_tokens": 300, "completion_tokens": 150}))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)
    assert section["reconciles"] is True
    agent = section["agentAttribution"]
    assert agent["available"] is True
    bucket_total = round(sum(float(i["cost"]) for i in agent["items"]), 6)
    assert abs(bucket_total - float(section["totalCost"])) <= 0.01


# --------------------------------------------------------------------------
# T026: analytics cost drill-down (costUsd)
# --------------------------------------------------------------------------

def test_cost_usd_prefers_estimate_then_falls_back_to_token_price() -> None:
    from app.api.routes.analytics import _cost_usd

    # non-zero estimate wins
    row = {"model_name": "gpt-5.2", "prompt_tokens": 1000, "completion_tokens": 500, "cost_estimate_usd": 0.123456789}
    assert _cost_usd(row) == round(0.123456789, 6)
    # zero / missing estimate -> MODEL_PRICES token pricing (gpt-5.2 = 35/110 per M)
    assert _cost_usd({"model_name": "gpt-5.2", "prompt_tokens": 1000000, "completion_tokens": 0}) == 35.0
    # unknown model -> DEFAULT_PRICE
    assert _cost_usd({"model_name": "unknown-model", "prompt_tokens": 1000000, "completion_tokens": 0}) == round(10.0, 6)
    # missing tokens -> zero
    assert _cost_usd({"model_name": "gpt-5.2"}) == 0.0


def test_token_usage_detail_exposes_cost_and_dimensions(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    from app.api.routes import analytics

    row = {
        "request_id": "req-1",
        "tenant_id": "tenant-1",
        "model_name": "gpt-5.2",
        "total_tokens": 150,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost_estimate_usd": 0.0123,
        "agent_id": "research.progressive",
        "skill_id": "v1",
        "workspace_id": "ws-42",
        "prompt": "hi",
        "request_payload": {},
        "response_payload": {},
    }
    db = _DB(token_usage_logs=_Coll([row]))
    monkeypatch.setattr(analytics, "get_db", lambda: db)

    import asyncio

    detail = asyncio.run(analytics.get_token_usage_detail("req-1", current_user={"tenant_id": "tenant-1"}))
    assert detail["costUsd"] == 0.0123
    assert detail["modelName"] == "gpt-5.2"
    assert detail["totalTokens"] == 150
    assert detail["agentId"] == "research.progressive"
    assert detail["skillId"] == "v1"
    assert detail["workspaceId"] == "ws-42"


def test_token_usage_detail_enforces_tenant_isolation(monkeypatch) -> None:
    _use_panwei_ids(monkeypatch)
    from app.api.routes import analytics

    row = {"request_id": "req-2", "tenant_id": "tenant-A", "prompt": "x"}
    db = _DB(token_usage_logs=_Coll([row]))
    monkeypatch.setattr(analytics, "get_db", lambda: db)

    import asyncio

    try:
        asyncio.run(analytics.get_token_usage_detail("req-2", current_user={"tenant_id": "tenant-B"}))
        raised = False
    except Exception:
        raised = True
    assert raised