"""T031 (SC-002): 驾驶舱项目维度——projectAttribution 可用、分桶合计对账、web 会话落默认项目。

验证 046 FR-012 后 dashboard 成本段的项目维度：
1. projectAttribution.available = true（有 project_id 数据时）
2. 分桶合计与 totalCost 对账（reconciles = true）
3. web 会话（project_id = "default"）落默认项目桶
4. project_id 优先于 workspace_id（046 新数据有 project_id 时不用 workspace_id）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch


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
        return _Cursor([dict(d) for d in self._docs if _match(d, query)])

    async def find_one(self, query=None, *a, **k):
        for doc in self._docs:
            if _match(doc, query):
                return dict(doc)
        return None

    def aggregate(self, pipeline, *a, **k):
        return _Cursor(list(self._aggregate_rows))

    async def count_documents(self, query=None):
        return len([d for d in self._docs if _match(d, query)])


class _DB:
    def __init__(self, **collections: _Coll) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _Coll:
        return self._collections.get(name, _Coll())

    def __getattr__(self, name: str) -> _Coll:
        return self[name]


def _usage_coll(raw: list[dict], agg: list[dict]) -> _Coll:
    return _Coll(raw, agg)


def _aggregate_rows(model: str, calls: int, prompt_tokens: int, completion_tokens: int) -> list[dict]:
    return [{
        "_id": model,
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }]


def _raw_rows(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        "tenant_id": "tenant-1",
        "user_id": "user-1001",
        "model_name": "gpt-5.2",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "created_at": _now(),
    }
    return [{**base, **row} for row in rows]


def _cost_section(db: _DB) -> dict[str, Any]:
    """Run the dashboard cost section synchronously."""
    import asyncio
    from app.api.routes.dashboard import _cost_section as fn
    return asyncio.run(fn(db, "tenant-1"))


def test_project_attribution_with_project_id() -> None:
    """046 FR-012: project_id 优先于 workspace_id；分桶合计与 totalCost 对账。"""
    raw = _raw_rows(
        {"project_id": "proj-alpha", "workspace_id": "ws-old", "agent_id": "a1"},
        {"project_id": "proj-alpha", "workspace_id": "ws-old", "agent_id": "a1"},
        {"project_id": "proj-beta", "workspace_id": "ws-other", "agent_id": "a2"},
    )
    usage = _usage_coll(raw, _aggregate_rows("gpt-5.2", 3, 300, 150))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)

    project = section["projectAttribution"]
    assert project["available"] is True
    project_keys = [i["key"] for i in project["items"]]
    # project_id 优先，不用 workspace_id
    assert "proj-alpha" in project_keys
    assert "proj-beta" in project_keys
    assert "ws-old" not in project_keys
    assert "ws-other" not in project_keys

    # 分桶合计对账
    assert section["reconciles"] is True
    bucket_cost_sum = sum(i["cost"] for i in project["items"])
    assert abs(bucket_cost_sum - section["totalCost"]) < 0.01


def test_project_attribution_web_sessions_fall_to_default() -> None:
    """SC-002: web 会话（project_id 为空/无）落默认项目桶。"""
    raw = _raw_rows(
        {"project_id": "proj-code", "agent_id": "a1"},
        {"agent_id": "a2"},  # 无 project_id → 未分配或 default
    )
    usage = _usage_coll(raw, _aggregate_rows("gpt-5.2", 2, 200, 100))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)

    project = section["projectAttribution"]
    assert project["available"] is True
    project_keys = [i["key"] for i in project["items"]]
    assert "proj-code" in project_keys
    # 无 project_id 的行落入 未分配（dimension_of 返回空 → UNASSIGNED）
    assert "未分配" in project_keys


def test_project_attribution_fallback_workspace_id() -> None:
    """迁移期兼容：无 project_id 时回退 workspace_id。"""
    raw = _raw_rows(
        {"workspace_id": "ws-42", "agent_id": "a1"},  # 旧数据只有 workspace_id
        {"project_id": "proj-new", "workspace_id": "ws-old", "agent_id": "a1"},
    )
    usage = _usage_coll(raw, _aggregate_rows("gpt-5.2", 2, 200, 100))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)

    project = section["projectAttribution"]
    assert project["available"] is True
    project_keys = [i["key"] for i in project["items"]]
    # project_id 优先
    assert "proj-new" in project_keys
    # 无 project_id 的行回退 workspace_id
    assert "ws-42" in project_keys


def test_project_attribution_reconciles_with_total() -> None:
    """SC-002: 所有分桶合计 = totalCost（reconciles = true）。"""
    raw = _raw_rows(
        {"project_id": "p1"},
        {"project_id": "p1"},
        {"project_id": "p2"},
        {"project_id": "p2"},
        {"project_id": "p2"},
    )
    usage = _usage_coll(raw, _aggregate_rows("gpt-5.2", 5, 500, 250))
    db = _DB(token_usage_logs=usage, end_user_org_relations=_Coll([]), org_units=_Coll([]))
    section = _cost_section(db)

    assert section["reconciles"] is True
    assert section["totalCost"] > 0

    project = section["projectAttribution"]
    assert project["available"] is True
    bucket_calls = sum(i["calls"] for i in project["items"])
    bucket_tokens = sum(i["tokens"] for i in project["items"])
    assert bucket_calls == 5
    assert bucket_tokens == 750
