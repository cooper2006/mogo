"""042-three-level-quota：三层（团队/项目/租户/用户）配额语义单测。

本文件在 ``services/chat-api/tests/`` 与 ``services/admin-api/tests/`` 各存一份
**同内容副本**（spec R-9：两侧断言同一 fixture 的 ``get_quota_summary`` 结果，
保证同名 ``quota_policy.py`` 副本行为一致）。

全部用 fake DB（无真实 Mongo 依赖），风格与 ``tests/test_eval_gate.py`` 一致。
"""

from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone

import pytest

from app.core import quota_policy


def async_test(func):
    """admin-api 未安装 pytest-asyncio；两侧文件同内容，统一用 asyncio.run 驱动。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------
# fake DB
# --------------------------------------------------------------------------

TENANT = "t1"
USER_ID = "u1"


def _naive(value):
    """两侧 period_window 的 tz-aware/naive 差异无关本测；比较前统一成 naive UTC。"""

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


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
                if "$set" in update:
                    self.rows[index] = {**row, **update["$set"]}
                return None
        if upsert:
            document = dict(query)
            document.update(update.get("$setOnInsert") or {})
            document.update(update.get("$set") or {})
            self.rows.append(document)
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


def _seed(db: _Db, collection: str, rows: list[dict]) -> None:
    db[collection].rows.extend(dict(row) for row in rows)


@pytest.fixture()
def db(monkeypatch) -> _Db:
    fake = _Db()
    _seed(
        fake,
        quota_policy.ORG_COLLECTION,
        [{"tenant_id": TENANT, "org_name": "组织空间", "space_type": "enterprise", "total_points": 0}],
    )
    _seed(
        fake,
        quota_policy.ORG_QUOTA_POLICY_COLLECTION,
        [{"tenant_id": TENANT, "total_tokens": 5000, "period": "monthly", "status": "active"}],
    )
    monkeypatch.setattr(quota_policy, "get_db", lambda: fake)
    return fake


def _user() -> dict:
    return {"_id": USER_ID, "space_type": "enterprise"}


def _policy(scope_type: str, scope_id: str, tokens: int, *, status: str = "active", name: str = "") -> dict:
    return {
        "tenant_id": TENANT,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "quota_tokens": tokens,
        "period": "monthly",
        "status": status,
        "name": name,
    }


def _usage(user_id: str, tokens: int) -> dict:
    return {
        "tenant_id": TENANT,
        "user_id": user_id,
        "total_tokens": tokens,
        "status": "success",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }


def _add_team(db: _Db, *, tokens: int, members: list[str], used: int, status: str = "active", name: str = "研发部") -> None:
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("team", "team-1", tokens, status=status, name=name)])
    _seed(db, quota_policy.USER_ORG_REL_COLLECTION, [{"tenant_id": TENANT, "user_id": member, "org_id": "team-1"} for member in members])
    for member in members:
        _seed(db, quota_policy.TOKEN_USAGE_COLLECTION, [_usage(member, used)])


def _add_project(db: _Db, *, project_id: str, tokens: int, members: list[str], used: int, status: str = "active", project_status: str = "active", name: str = "专项") -> None:
    _seed(
        db,
        quota_policy.QUOTA_PROJECT_COLLECTION,
        [{"_id": project_id, "tenant_id": TENANT, "name": name, "member_user_ids": list(members), "status": project_status}],
    )
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("project", project_id, tokens, status=status, name=name)])
    for member in members:
        _seed(db, quota_policy.TOKEN_USAGE_COLLECTION, [_usage(member, used)])


# --------------------------------------------------------------------------
# US3 / SC-001：四层取小
# --------------------------------------------------------------------------


@async_test
async def test_three_level_min_matrix(db):
    _add_team(db, tokens=1000, members=[USER_ID], used=100)
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    # team: 1000-100=900 < org: 5000-0=5000 < user: 3000-0=3000
    assert summary["remainingPoints"] == 900
    assert summary["limitingScope"] == "team"
    assert summary["teamRemainingPoints"] == 900
    assert summary["teamTotalPoints"] == 1000
    assert summary["teamUsedPoints"] == 100
    # 既有字段不漂移
    assert summary["orgTotalPoints"] == 5000
    assert summary["totalPoints"] == 3000


@async_test
async def test_multi_project_takes_strictest(db):
    _add_project(db, project_id="p1", tokens=1000, members=[USER_ID], used=900, name="专项A")
    _add_project(db, project_id="p2", tokens=2000, members=[USER_ID], used=0, name="专项B")
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    assert summary["projectRemainingPoints"] == 100
    assert summary["limitingScope"] == "project"


@async_test
async def test_unconfigured_layers_stay_absent(db):
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    # R-6：未配置层整组字段不出现（不写 null / 0 / -1）
    assert "teamRemainingPoints" not in summary
    assert "projectRemainingPoints" not in summary
    assert "limitingScope" not in summary
    assert summary["remainingPoints"] == 3000


@async_test
async def test_disabled_team_layer_ignored(db):
    _add_team(db, tokens=1000, members=[USER_ID], used=1000, status="disabled")
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    assert "teamRemainingPoints" not in summary
    # 团队层被跳过；但该成员的 usage 仍计入 user/org 层窗口用量（1000）
    assert summary["remainingPoints"] == 2000


@async_test
async def test_deleted_project_layer_ignored(db):
    _add_project(db, project_id="p1", tokens=100, members=[USER_ID], used=100, project_status="deleted")
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    assert "projectRemainingPoints" not in summary


@async_test
async def test_points_unlimited_short_circuit_wins(db):
    # 两份副本的 unlimited 载体不同（chat-api 看 organizations.points_unlimited，
    # admin-api 看 org_quota_policies.unlimited），两侧都置位以保持本文件同内容。
    db[quota_policy.ORG_COLLECTION].rows[0]["points_unlimited"] = True
    db[quota_policy.ORG_QUOTA_POLICY_COLLECTION].rows[0]["unlimited"] = True
    _add_team(db, tokens=1000, members=[USER_ID], used=1000)
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    assert summary["unlimited"] is True
    assert summary["remainingPoints"] == -1
    assert "teamRemainingPoints" not in summary


# --------------------------------------------------------------------------
# US3 / SC-002：单层超限即拒且指明层
# --------------------------------------------------------------------------


@async_test
async def test_assert_blocks_on_team_layer(db):
    _add_team(db, tokens=1000, members=[USER_ID], used=1000)
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    with pytest.raises(quota_policy.QuotaExceededError) as excinfo:
        await quota_policy.assert_quota_available(TENANT, _user())
    assert excinfo.value.layer == "team"
    assert "团队额度已用尽" in str(excinfo.value)
    assert "研发部" in str(excinfo.value)


@async_test
async def test_assert_blocks_on_project_layer(db):
    _add_project(db, project_id="p1", tokens=500, members=[USER_ID], used=500, name="专项A")
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    with pytest.raises(quota_policy.QuotaExceededError) as excinfo:
        await quota_policy.assert_quota_available(TENANT, _user())
    assert excinfo.value.layer == "project"
    assert "项目额度已用尽" in str(excinfo.value)


@async_test
async def test_assert_keeps_legacy_org_message(db):
    db[quota_policy.ORG_QUOTA_POLICY_COLLECTION].rows[0]["total_tokens"] = 0
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    db[quota_policy.ORG_QUOTA_POLICY_COLLECTION].rows[0]["total_tokens"] = 500
    _seed(db, quota_policy.TOKEN_USAGE_COLLECTION, [_usage(USER_ID, 500)])
    with pytest.raises(quota_policy.QuotaExceededError) as excinfo:
        await quota_policy.assert_quota_available(TENANT, _user())
    assert "企业分派额度已用尽" in str(excinfo.value)


# --------------------------------------------------------------------------
# US4 / SC-004：告警产出与去重
# --------------------------------------------------------------------------


@async_test
async def test_approaching_alert_written_once(db):
    _add_team(db, tokens=1000, members=[USER_ID], used=850)
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    await quota_policy.get_quota_summary(TENANT, _user())
    await quota_policy.get_quota_summary(TENANT, _user())
    rows = [row for row in db[quota_policy.QUOTA_ALERT_COLLECTION].rows if row.get("kind") == "approaching"]
    assert len(rows) == 1
    assert rows[0]["scope_type"] == "team"
    assert rows[0]["scope_id"] == "team-1"
    assert rows[0]["ratio"] == pytest.approx(0.15, abs=1e-6)


@async_test
async def test_exceeded_alert_written_once(db):
    _add_team(db, tokens=1000, members=[USER_ID], used=1000)
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    for _ in range(3):
        await quota_policy.get_quota_summary(TENANT, _user())
    rows = [row for row in db[quota_policy.QUOTA_ALERT_COLLECTION].rows if row.get("kind") == "exceeded"]
    assert len(rows) == 1
    assert rows[0]["alert_key"].startswith(f"{TENANT}:team:team-1:exceeded:")


@async_test
async def test_alert_kinds_constant_matches_spec(db):
    assert quota_policy.QUOTA_ALERT_KINDS == ("exceeded", "approaching", "layer_unreadable")


# --------------------------------------------------------------------------
# SC-003：零 team/project 策略时输出逐字段等价
# --------------------------------------------------------------------------


@async_test
async def test_zero_scoped_policies_keeps_legacy_shape(db):
    _seed(db, quota_policy.USER_QUOTA_POLICY_COLLECTION, [_policy("user", USER_ID, 3000)])
    _seed(db, quota_policy.TOKEN_USAGE_COLLECTION, [_usage(USER_ID, 1000)])
    summary = await quota_policy.get_quota_summary(TENANT, _user())
    required_keys = {
        "tenantId",
        "orgName",
        "spaceType",
        "quotaSource",
        "period",
        "totalPoints",
        "usedPoints",
        "remainingPoints",
        "resetAt",
        "status",
        "orgTotalPoints",
        "orgUsedPoints",
        "orgRemainingPoints",
    }
    assert required_keys.issubset(set(summary))
    # 042 只允许新增 team*/project*/limiting* 字段；其余键必须与改造前一致
    # （chat-api 额外带 product_edition_fields 的 edition/billingEnabled/memberLimit，
    #  admin-api 副本没有——两份副本的既有差异，与本特性无关）。
    allowed_extra = {
        "unlimited",
        "edition",
        "billingEnabled",
        "memberLimit",
        "teamRemainingPoints",
        "teamTotalPoints",
        "teamUsedPoints",
        "teamResetAt",
        "teamScopeId",
        "teamName",
        "projectRemainingPoints",
        "projectTotalPoints",
        "projectUsedPoints",
        "projectResetAt",
        "projectScopeId",
        "projectName",
        "limitingScope",
        "limitingResetAt",
    }
    assert set(summary) - required_keys <= allowed_extra
    assert summary["remainingPoints"] == 2000
    assert summary["status"] == "active"
