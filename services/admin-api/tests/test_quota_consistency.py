"""047 T022 静态一致性矩阵 + 049 T019 双服务项目层运行时对拍。

上半部分：不 mock 数据库，提取两侧返回 dict 的 key 集合做静态对比，
加上对已知字段（totalPoints / remainingPoints / quotaSource 等）的语义比对。

下半部分（049 T019 严格收口）：用同一份 fake DB fixture 分别驱动
admin-api / chat-api 的 ``get_quota_summary``，逐字段比对 project 层的
total / used / remaining，并捕获传给 ``sum_usage`` 的 ``user_ids``，
把「projects.member_user_ids ∪ 创建者」锁成运行时行为而非源码文本。
"""
from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import importlib.util
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

ADMIN_QUOTA = ROOT / "services" / "admin-api" / "app" / "core" / "quota_policy.py"
CHAT_QUOTA = ROOT / "services" / "chat-api" / "app" / "core" / "quota_policy.py"

# 期望两侧共有的核心字段（FR 要求语义一致）
EXPECTED_KEYS = {
    "tenantId", "orgName", "spaceType", "quotaSource", "period",
    "totalPoints", "usedPoints", "remainingPoints",
}


def _extract_return_keys(filepath: Path) -> set[str]:
    """Extract string keys from return dicts in get_quota_summary."""
    source = filepath.read_text()
    tree = ast.parse(source)
    keys: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_quota_summary":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    for key in child.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
    return keys


def _extract_string_values(filepath: Path, pattern: str) -> list[str]:
    """Extract string values matching a pattern from source."""
    source = filepath.read_text()
    return re.findall(pattern, source)


class TestQuotaSummaryKeyConsistency:
    """Compare get_quota_summary return keys between admin-api and chat-api."""

    def test_admin_api_has_expected_keys(self):
        keys = _extract_return_keys(ADMIN_QUOTA)
        missing = EXPECTED_KEYS - keys
        assert not missing, f"admin-api missing keys: {missing}"

    def test_chat_api_has_expected_keys(self):
        keys = _extract_return_keys(CHAT_QUOTA)
        missing = EXPECTED_KEYS - keys
        assert not missing, f"chat-api missing keys: {missing}"

    def test_both_sides_share_common_keys(self):
        admin_keys = _extract_return_keys(ADMIN_QUOTA)
        chat_keys = _extract_return_keys(CHAT_QUOTA)
        common = admin_keys & chat_keys
        missing_common = EXPECTED_KEYS - common
        assert not missing_common, (
            f"Keys in EXPECTED_KEYS but not shared: {missing_common}\n"
            f"  admin-api only: {sorted(admin_keys - chat_keys)}\n"
            f"  chat-api only: {sorted(chat_keys - admin_keys)}"
        )

    def test_report_key_differences(self):
        """T023: 记录差异清单（不作为硬断言，只打印）。"""
        admin_keys = _extract_return_keys(ADMIN_QUOTA)
        chat_keys = _extract_return_keys(CHAT_QUOTA)
        admin_only = sorted(admin_keys - chat_keys)
        chat_only = sorted(chat_keys - admin_keys)
        if admin_only or chat_only:
            print(f"\nadmin-api only keys: {admin_only}")
            print(f"chat-api only keys: {chat_only}")

    def test_quota_source_values_consistent(self):
        """Both sides should use the same quotaSource values."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            values = _extract_string_values(filepath, r'"quotaSource":\s*"([^"]+)"')
            assert len(values) > 0, f"{label}: no quotaSource values found"
            for v in values:
                assert v in (
                    "registration_gift", "enterprise_allocation",
                    "unlimited", "personal",
                ), f"{label}: unexpected quotaSource '{v}'"

    def test_points_unlimited_default_consistent(self):
        """Both sides should use `points_unlimited, True` (default unlimited)."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert re.search(r'points_unlimited["\s,]+True', source), (
                f"{label}: points_unlimited should default to True"
            )

    def test_denial_message_consistent(self):
        """Both sides use 部门额度已用尽 (not 团队)."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert "部门额度已用尽" in source, f"{label}: should use 部门额度已用尽"
            assert "团队额度已用尽" not in source, f"{label}: should NOT use 团队额度已用尽"

class TestProjectMemberScopeConsistency:
    """049 T019: 项目成员口径两侧一致（FR-006）。

    两侧 ``quota_policy`` 都必须：读 ``projects`` 集合、把 ``member_user_ids``
    与创建者 ``user_id`` 合并为项目层成员、archived 项目不参与取小。
    """

    def test_both_sides_read_projects_collection(self):
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert re.search(r'PROJECT_COLLECTION\s*=\s*"projects"', source), (
                f"{label}: 项目层必须读 046 的 projects 集合"
            )
            # 注释里可以提退役，但不能再有实际读写：常量赋值 / 集合访问。
            assert not re.search(r'=\s*"quota_projects"', source), (
                f"{label}: 049 后不应再把 quota_projects 作为集合常量"
            )
            assert '["quota_projects"]' not in source, (
                f"{label}: 049 后不应再访问 quota_projects 集合"
            )

    def test_both_sides_merge_members_with_creator(self):
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert "member_user_ids" in source, f"{label}: 项目成员口径缺 member_user_ids"
            assert "creator_id" in source or 'get("user_id")' in source, (
                f"{label}: 项目成员口径必须并入创建者 user_id"
            )

    def test_both_sides_skip_archived_projects(self):
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert re.search(r'"archived"', source), (
                f"{label}: archived 项目必须跳过（046 US2 / 049 FR-006）"
            )
            assert not re.search(r'"deleted"\s*\]?\)?\s*:?\s*return', source), (
                f"{label}: 不应再按 deleted 判定项目层失效"
            )


# ---------------------------------------------------------------------------
# 049 T019: 同 fixture 下双服务 get_quota_summary 项目层运行时对拍
# ---------------------------------------------------------------------------

TENANT = "t1"
OWNER = "owner"
MEMBER_A = "m1"
MEMBER_B = "m2"
OUTSIDER = "outsider"
PROJECT_ID = "p1"

_ADMIN_MODULE_NAME = "_049_admin_quota_under_test"
_CHAT_MODULE_NAME = "_049_chat_quota_under_test"

# 固定周期窗口，避免跨月边界 flaky；两侧 period_window 的 tz-aware/naive 差异一并归一。
_FIXED_START = datetime(2026, 10, 31, 16, 0, 0, tzinfo=timezone.utc)
_FIXED_END = datetime(2026, 11, 30, 16, 0, 0, tzinfo=timezone.utc)
_FIXED_NOW = datetime(2026, 11, 5, 2, 0, 0, tzinfo=timezone.utc)

PROJECT_FIELDS = (
    "projectTotalPoints",
    "projectUsedPoints",
    "projectRemainingPoints",
    "projectScopeId",
    "projectName",
    "projectResetAt",
)


def _fixed_window(period, tz_name=None, now=None):
    return _FIXED_START, _FIXED_END


def _naive(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _match_value(value, expected) -> bool:
    if isinstance(expected, dict):
        for operator, operand in expected.items():
            if operator == "$ne" and value == operand:
                return False
            if operator == "$in" and value not in operand:
                return False
            if operator in ("$gte", "$lt", "$gt"):
                if value is None:
                    return False
                left, right = _naive(value), _naive(operand)
                if operator == "$gte" and left < right:
                    return False
                if operator == "$lt" and left >= right:
                    return False
                if operator == "$gt" and left <= right:
                    return False
            if operator == "$exists":
                if operand and value is None:
                    return False
                if not operand and value is not None:
                    return False
        return True
    if isinstance(value, list):
        return expected in value
    return value == expected


def _matches(row: dict, query: dict | None) -> bool:
    for key, expected in (query or {}).items():
        if key == "$or":
            if not any(_matches(row, branch) for branch in expected):
                return False
        elif not _match_value(row.get(key), expected):
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

    async def find_one(self, query: dict | None = None, projection=None, sort=None) -> dict | None:
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query: dict | None = None, projection=None) -> _Cursor:
        return _Cursor([dict(row) for row in self.rows if _matches(row, query)])

    def aggregate(self, pipeline: list[dict]) -> _Cursor:
        rows = list(self.rows)
        sum_field = "total_tokens"
        for stage in pipeline:
            if "$match" in stage:
                rows = [row for row in rows if _matches(row, stage["$match"])]
            group = stage.get("$group") or {}
            expression = (group.get("tokens") or {}).get("$sum") or {}
            if isinstance(expression, dict) and "$ifNull" in expression:
                sum_field = str(expression["$ifNull"][0]).lstrip("$")
        if not rows:
            return _Cursor([])
        return _Cursor([{"_id": None, "tokens": sum(int(row.get(sum_field) or 0) for row in rows)}])

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
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


class _Db:
    def __init__(self, seed: dict[str, list[dict]]) -> None:
        self._collections = {name: _Collection(rows) for name, rows in seed.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


def _stub_module(monkeypatch, dotted: str, **attrs):
    """在 sys.modules 注入（或复用）包链，供跨服务模块导入期解析依赖。

    chat-api 的 quota_policy 依赖 app.infrastructure.observability.config 与
    app.core.product_edition；这两条链在 admin-api 测试环境里不一定存在，
    因此按叶子模块逐层补齐，测试结束由 monkeypatch 自动还原。
    """

    parts = dotted.split(".")
    parent = None
    module = None
    for index in range(1, len(parts) + 1):
        name = ".".join(parts[:index])
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            monkeypatch.setitem(sys.modules, name, module)
        if parent is not None:
            monkeypatch.setattr(parent, parts[index - 1], module, raising=False)
        parent = module
    for key, value in attrs.items():
        monkeypatch.setattr(module, key, value, raising=False)
    return module


def _load_quota_module(path: Path, name: str, monkeypatch):
    """按唯一模块名从文件加载 quota_policy，绕开两侧同名 app.core.quota_policy。"""

    importlib.import_module("app.core.db")  # 确保真实 app / app.core / app.core.db 链已就绪
    _stub_module(monkeypatch, "app.infrastructure.observability.config", log_print=lambda *a, **kw: None)
    _stub_module(monkeypatch, "app.core.product_edition", product_edition_fields=lambda org: {})
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _usage_row(user_id: str, tokens: int) -> dict:
    return {
        "tenant_id": TENANT,
        "user_id": user_id,
        "total_tokens": tokens,
        "created_at": _FIXED_NOW,
        "status": "ok",
    }


def _seed_documents(*, project: dict, sessions: list[dict], usage: list[dict]) -> dict[str, list[dict]]:
    """两个服务各拿一份深拷贝，保证「同 fixture」且互不污染。"""

    return {
        "organizations": [
            {
                "tenant_id": TENANT,
                "org_name": "组织空间",
                "space_type": "enterprise",
                "total_points": 0,
                "points_unlimited": False,
            }
        ],
        "org_quota_policies": [
            {
                "tenant_id": TENANT,
                "total_tokens": 100000,
                "period": "monthly",
                "status": "active",
                "timezone": "Asia/Shanghai",
                "unlimited": False,
            }
        ],
        "user_quota_policies": [
            {
                "tenant_id": TENANT,
                "scope_type": "user",
                "scope_id": OWNER,
                "quota_tokens": 100000,
                "period": "monthly",
                "status": "active",
                "priority": 0,
                "updated_at": _FIXED_NOW,
            },
            {
                "tenant_id": TENANT,
                "scope_type": "project",
                "scope_id": PROJECT_ID,
                "quota_tokens": 1000,
                "period": "monthly",
                "status": "active",
                "name": "项目 A",
                "priority": 0,
                "updated_at": _FIXED_NOW,
            },
        ],
        "user_quota_overrides": [],
        "end_user_org_relations": [],
        "chat_sessions": sessions,
        "projects": [project],
        "quota_alert_events": [],
        "token_usage_logs": usage,
    }


class _RuntimePair:
    """分别驱动两侧 get_quota_summary，并捕获项目层 sum_usage 的 user_ids。"""

    def __init__(self, monkeypatch) -> None:
        self.admin = _load_quota_module(ADMIN_QUOTA, _ADMIN_MODULE_NAME, monkeypatch)
        self.chat = _load_quota_module(CHAT_QUOTA, _CHAT_MODULE_NAME, monkeypatch)
        self._monkeypatch = monkeypatch

    def _run_one(self, module, seed: dict[str, list[dict]]):
        db = _Db(copy.deepcopy(seed))
        calls: list[tuple[tuple[str, ...], int]] = []
        self._monkeypatch.setattr(module, "get_db", lambda: db, raising=False)
        self._monkeypatch.setattr(module, "period_window", _fixed_window, raising=False)
        original_sum_usage = module.sum_usage

        async def spying_sum_usage(tenant_id, **kwargs):
            used = await original_sum_usage(tenant_id, **kwargs)
            if kwargs.get("user_ids") is not None:
                calls.append((tuple(kwargs["user_ids"]), used))
            return used

        self._monkeypatch.setattr(module, "sum_usage", spying_sum_usage, raising=False)
        summary = asyncio.run(
            module.get_quota_summary(TENANT, {"_id": OWNER, "space_type": "enterprise"})
        )
        return summary, calls

    def run(self, seed: dict[str, list[dict]]):
        admin_summary, admin_calls = self._run_one(self.admin, seed)
        chat_summary, chat_calls = self._run_one(self.chat, seed)
        return admin_summary, chat_summary, admin_calls, chat_calls


def _project_view(summary: dict) -> dict:
    return {key: summary.get(key) for key in PROJECT_FIELDS}


@pytest.fixture()
def runtime_pair(monkeypatch) -> _RuntimePair:
    return _RuntimePair(monkeypatch)


class TestProjectLayerRuntimeConsistency:
    """049 T019: 真正跑两侧 quota_policy，而非只比对源码文本。"""

    @staticmethod
    def _active_project(**overrides) -> dict:
        project = {
            "tenant_id": TENANT,
            "_id": PROJECT_ID,
            "user_id": OWNER,
            "member_user_ids": [MEMBER_A, MEMBER_B],
            "status": "active",
            "title": "项目 A",
        }
        project.update(overrides)
        return project

    @staticmethod
    def _usage() -> list[dict]:
        # 项目成员∪创建者 = 100 + 200 + 300 = 600；非成员 4000 必须被排除。
        return [
            _usage_row(OWNER, 100),
            _usage_row(MEMBER_A, 200),
            _usage_row(MEMBER_B, 300),
            _usage_row(OUTSIDER, 4000),
        ]

    @staticmethod
    def _sessions() -> list[dict]:
        # _project_scope_ids（用户→项目）反查，保证项目层策略进入 _scoped_layers。
        return [{"tenant_id": TENANT, "user_id": OWNER, "project_id": PROJECT_ID}]

    def test_members_union_creator_yields_same_total_used_remaining(self, runtime_pair):
        seed = _seed_documents(
            project=self._active_project(),
            sessions=self._sessions(),
            usage=self._usage(),
        )
        admin, chat, admin_calls, chat_calls = runtime_pair.run(seed)

        assert _project_view(admin) == _project_view(chat), "两侧 project 层字段必须逐字段一致"
        assert admin["projectTotalPoints"] == 1000
        assert admin["projectUsedPoints"] == 600, "用量 = 成员∪创建者，不含非成员"
        assert admin["projectRemainingPoints"] == 400
        assert admin["projectScopeId"] == PROJECT_ID
        assert admin.get("limitingScope") == "project", "项目层限额必须参与三层取小"
        assert admin["remainingPoints"] == 400
        assert admin_calls == chat_calls == [((MEMBER_A, MEMBER_B, OWNER), 600)]

    def test_project_without_members_uses_creator_only(self, runtime_pair):
        project = self._active_project()
        project.pop("member_user_ids")  # 046 时代 / 迁移期数据
        seed = _seed_documents(
            project=project,
            sessions=self._sessions(),
            usage=self._usage(),
        )
        admin, chat, admin_calls, chat_calls = runtime_pair.run(seed)

        assert _project_view(admin) == _project_view(chat)
        assert admin["projectUsedPoints"] == 100, "无成员项目 = 仅创建者口径"
        assert admin["projectRemainingPoints"] == 900
        assert admin_calls == chat_calls == [((OWNER,), 100)]

    def test_creator_listed_twice_is_deduplicated(self, runtime_pair):
        seed = _seed_documents(
            project=self._active_project(
                member_user_ids=[OWNER, MEMBER_A, OWNER, MEMBER_B]
            ),
            sessions=self._sessions(),
            usage=self._usage(),
        )
        admin, chat, admin_calls, chat_calls = runtime_pair.run(seed)

        assert _project_view(admin) == _project_view(chat)
        assert admin["projectUsedPoints"] == 600
        assert admin_calls == chat_calls == [((OWNER, MEMBER_A, MEMBER_B), 600)]

    def test_archived_project_layer_absent_on_both_sides(self, runtime_pair):
        seed = _seed_documents(
            project=self._active_project(status="archived"),
            sessions=self._sessions(),
            usage=self._usage(),
        )
        admin, chat, admin_calls, chat_calls = runtime_pair.run(seed)

        assert _project_view(admin) == _project_view(chat)
        assert all(value is None for value in _project_view(admin).values())
        assert admin_calls == chat_calls == [], "archived 项目不应再统计项目层用量"
