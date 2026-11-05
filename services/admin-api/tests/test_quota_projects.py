"""042-three-level-quota：项目分组服务与团队/项目策略端点单测（admin-api）。

fake DB 驱动，无真实 Mongo 依赖；风格与 ``tests/test_quota_three_level.py`` 一致。
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.routes import traffic_allocations as routes
from app.core import quota_policy
from app.services import quota_projects as projects


def async_test(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


TENANT = "t1"
ADMIN = {"tenant_id": TENANT, "username": "admin"}


def _match_value(value, expected) -> bool:
    if isinstance(expected, dict):
        if "$ne" in expected:
            return value != expected["$ne"]
        if "$in" in expected:
            return value in expected["$in"]
        if "$gte" in expected or "$lt" in expected:
            if value is None:
                return False
            current = _naive(value)
            if "$gte" in expected and current < _naive(expected["$gte"]):
                return False
            if "$lt" in expected and current >= _naive(expected["$lt"]):
                return False
            return True
        return True
    if isinstance(value, list):
        return expected in value
    return value == expected


def _naive(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _matches(row: dict, query: dict | None) -> bool:
    for key, expected in (query or {}).items():
        if not _match_value(row.get(key), expected):
            return False
    return True


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = list(rows)

    async def to_list(self, length: int | None = None) -> list[dict]:
        return list(self._rows if length is None else self._rows[:length])


class _Collection:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = [dict(row) for row in (rows or [])]

    async def find_one(self, query: dict | None = None, sort=None) -> dict | None:
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query: dict | None = None, projection=None) -> _Cursor:
        return _Cursor([dict(row) for row in self.rows if _matches(row, query)])

    def aggregate(self, pipeline: list[dict]) -> _Cursor:
        rows = self.rows
        for stage in pipeline:
            if "$match" in stage:
                rows = [row for row in rows if _matches(row, stage["$match"])]
        total = sum(int(row.get("total_tokens") or 0) for row in rows)
        return _Cursor([{"_id": None, "tokens": total}] if rows else [])

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = {**row, **(update.get("$set") or {})}
                return None
        if upsert:
            merged = dict(query)
            merged.update(update.get("$setOnInsert") or {})
            merged.update(update.get("$set") or {})
            self.rows.append(merged)
        return None

    async def insert_one(self, document: dict):
        self.rows.append(dict(document))
        return None

    async def delete_one(self, query: dict):
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return None


class _Db:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def __getitem__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())

    def __getattr__(self, name: str) -> _Collection:
        return self[name]


@pytest.fixture()
def db(monkeypatch) -> _Db:
    fake = _Db()
    fake[quota_policy.ORG_COLLECTION].rows.append(
        {"tenant_id": TENANT, "org_name": "组织空间", "space_type": "enterprise", "total_points": 0}
    )
    fake[quota_policy.ORG_QUOTA_POLICY_COLLECTION].rows.append(
        {"tenant_id": TENANT, "total_tokens": 10000, "period": "monthly", "status": "active"}
    )
    fake[routes.DEPARTMENT_COLLECTION].rows.append(
        {"_id": "dept-1", "tenant_id": TENANT, "name": "研发部"}
    )
    monkeypatch.setattr(projects, "get_db", lambda: fake)
    monkeypatch.setattr(routes, "get_db", lambda: fake)
    monkeypatch.setattr(quota_policy, "get_db", lambda: fake)
    return fake


# --------------------------------------------------------------------------
# T013：项目分组 CRUD
# --------------------------------------------------------------------------


@async_test
async def test_list_projects_reads_projects_collection(db):
    """049 T004：项目读路径切到 046 的 projects 表（name ← title）。"""
    db[projects.PROJECT_COLLECTION].rows.extend([
        {"_id": "proj-a", "tenant_id": TENANT, "user_id": "u9", "title": "专项A",
         "status": "active", "member_user_ids": ["u1", "u2"]},
        {"_id": "proj-b", "tenant_id": TENANT, "user_id": "u9", "title": "专项B",
         "status": "archived", "member_user_ids": []},
        {"_id": "proj-x", "tenant_id": "other", "user_id": "u9", "title": "别的租户",
         "status": "active", "member_user_ids": []},
    ])
    listed = await projects.list_projects(TENANT)
    assert {item["name"] for item in listed} == {"专项A", "专项B"}  # archived 也返回给前端分组
    active = next(item for item in listed if item["id"] == "proj-a")
    assert active["memberCount"] == 2
    assert active["memberUserIds"] == ["u1", "u2"]
    assert active["status"] == "active"
    assert next(item for item in listed if item["id"] == "proj-b")["status"] == "archived"


@async_test
async def test_project_writes_are_retired(db):
    """049 FR-007：写路径退役——服务层 RuntimeError + 三个写路由不再注册。"""
    with pytest.raises(RuntimeError):
        await projects.create_project(TENANT, name="专项A")
    with pytest.raises(RuntimeError):
        await projects.update_project(TENANT, "proj-a", name="专项B")
    with pytest.raises(RuntimeError):
        await projects.delete_project(TENANT, "proj-a")

    registered = {
        (method, route.path)
        for route in routes.router.routes
        for method in (getattr(route, "methods", None) or ())
    }
    retired = {
        ("POST", "/projects"),
        ("PUT", "/projects/{project_id}"),
        ("DELETE", "/projects/{project_id}"),
    }
    assert retired.isdisjoint(registered), f"049 后项目写端点应下线，仍注册: {retired & registered}"
    assert not any(
        hasattr(routes, name)
        for name in (
            "create_quota_project_gone",
            "update_quota_project_gone",
            "delete_quota_project_gone",
        )
    )


@async_test
async def test_archived_project_policy_endpoint_404(db):
    """049 FR-008：已归档项目不再接受配额策略写入（404）。"""
    db[projects.PROJECT_COLLECTION].rows.append(
        {"_id": "proj-old", "tenant_id": TENANT, "user_id": "u9", "title": "旧项目",
         "status": "archived", "member_user_ids": []}
    )
    with pytest.raises(HTTPException) as excinfo:
        await routes.update_project_quota_policy(
            "proj-old", routes.ProjectPolicyPayload(quotaTokens=100), current_user=ADMIN
        )
    assert excinfo.value.status_code == 404


@async_test
async def test_project_members_truncate_and_validate(db):
    assert projects.normalize_members(["a", "", "a", None, "b"]) == ["a", "b"]
    assert projects.normalize_members("not-a-list") == []


# --------------------------------------------------------------------------
# T014：团队/项目端点落库 + 审计
# --------------------------------------------------------------------------


@async_test
async def test_team_policy_endpoint_writes_policy_and_log(db):
    payload = routes.TeamPolicyPayload(quotaTokens=1000, period="daily", status="active")
    result = await routes.update_team_quota_policy("dept-1", payload, current_user=ADMIN)
    assert result["scopeType"] == "team"
    assert result["scopeId"] == "dept-1"
    assert result["name"] == "研发部"
    assert result["quotaTokens"] == 1000

    stored = db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows
    team_rows = [row for row in stored if row.get("scope_type") == "team"]
    assert len(team_rows) == 1
    assert team_rows[0]["period"] == "daily"

    logs = db[quota_policy.USER_QUOTA_LOG_COLLECTION].rows
    assert logs[-1]["action"] == "setup_team"
    assert logs[-1]["user_id"] == "team:dept-1"

    listed = await routes.list_team_policies(current_user=ADMIN)
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "研发部"


@async_test
async def test_team_policy_unknown_department_404(db):
    payload = routes.TeamPolicyPayload(quotaTokens=100)
    with pytest.raises(HTTPException) as excinfo:
        await routes.update_team_quota_policy("missing", payload, current_user=ADMIN)
    assert excinfo.value.status_code == 404


@async_test
async def test_project_policy_endpoint_writes_policy_and_log(db):
    db[projects.PROJECT_COLLECTION].rows.append(
        {"_id": "proj-1", "tenant_id": TENANT, "user_id": "u9", "title": "专项A",
         "status": "active", "member_user_ids": ["u1"]}
    )
    project_id = "proj-1"
    payload = routes.ProjectPolicyPayload(quotaTokens=2000)
    result = await routes.update_project_quota_policy(project_id, payload, current_user=ADMIN)
    assert result["scopeType"] == "project"
    assert result["name"] == "专项A"

    project_rows = [
        row
        for row in db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows
        if row.get("scope_type") == "project"
    ]
    assert len(project_rows) == 1
    assert project_rows[0]["quota_tokens"] == 2000

    actions = [row["action"] for row in db[quota_policy.USER_QUOTA_LOG_COLLECTION].rows]
    assert "setup_project" in actions


@async_test
async def test_delete_team_policy_removes_row_and_logs(db):
    payload = routes.TeamPolicyPayload(quotaTokens=500)
    await routes.update_team_quota_policy("dept-1", payload, current_user=ADMIN)
    await routes.delete_team_quota_policy("dept-1", current_user=ADMIN)
    team_rows = [
        row
        for row in db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows
        if row.get("scope_type") == "team"
    ]
    assert team_rows == []
    assert db[quota_policy.USER_QUOTA_LOG_COLLECTION].rows[-1]["action"] == "delete_team"


@async_test
async def test_overview_exposes_scoped_counts_without_touching_user_totals(db):
    db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows.append(
        {
            "tenant_id": TENANT,
            "scope_type": "team",
            "scope_id": "dept-1",
            "quota_tokens": 700,
            "period": "monthly",
            "status": "active",
        }
    )
    db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows.append(
        {
            "tenant_id": TENANT,
            "scope_type": "project",
            "scope_id": "proj-1",
            "quota_tokens": 300,
            "period": "monthly",
            "status": "active",
        }
    )
    db[quota_policy.USER_QUOTA_POLICY_COLLECTION].rows.append(
        {
            "tenant_id": TENANT,
            "scope_type": "user",
            "scope_id": "u1",
            "quota_tokens": 100,
            "period": "monthly",
            "status": "active",
        }
    )
    overview = await routes.get_traffic_allocation_overview(current_user=ADMIN)
    assert overview["teamPolicyCount"] == 1
    assert overview["teamAssignedTokens"] == 700
    assert overview["projectPolicyCount"] == 1
    assert overview["projectAssignedTokens"] == 300
    # R-14：既有字段语义不变——assignedTokens 仍只统计 user 层，且沿用
    # "仅计入真实存在的成员"过滤（本 fixture 无 end_users 行，故为 0；
    # team/project 层的 700/300 不得混入该字段）。
    assert overview["assignedTokens"] == 0
    assert overview["assignedPolicyCount"] == 0
    assert overview["alertThresholdRatio"] == pytest.approx(0.2)


@async_test
async def test_org_policy_persists_alert_threshold(db):
    payload = routes.OrgQuotaPayload(totalTokens=9000, alertThresholdRatio=0.35)
    await routes.update_org_quota_policy(payload, current_user=ADMIN)
    row = db[quota_policy.ORG_QUOTA_POLICY_COLLECTION].rows[0]
    assert row["alert_threshold_ratio"] == pytest.approx(0.35)
    assert row["total_tokens"] == 9000
