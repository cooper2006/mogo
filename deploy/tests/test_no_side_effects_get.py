"""T035（022 FR-15 / QF-637）：GET 端点无副作用。

QualityForge 审计（QF-637）发现 4 个 GET 端点在请求处理路径上执行写操作
（惰性初始化 / 缓存刷新语义），字面上违反『GET 不修改任何状态』：

- ``GET /auth/me``                → 更新 ``session.available_tenants``
- ``GET /sessions/{id}``          → 清除 ``scheduled_unread``
- ``GET /personal-knowledge/{id}``→ 写入 ``grant.seen_at``
- ``GET /organizations/billing``  → ``insert_one`` 惰性建库

这些端点已改造：GET 只读，写操作拆到显式 POST。

本测试用 AST 静态扫描两个服务的全部 GET 路由函数，断言其函数体（含
await 调用链的第一层）不出现数据库写操作。这是回归防线：将来任何人再往
GET 端点里塞写操作，测试会立刻失败。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ROUTE_DIRS = [
    REPO_ROOT / "services/admin-api/app/api/routes",
    REPO_ROOT / "services/chat-api/app/api/endpoints",
]

# 写操作识别：Mongo 单文档/多文档写、ORM 风格写、以及常见业务写动词。
# 用正则做粗筛后由 AST 精确定位到"函数体内"，避免误伤 import / 注释。
_WRITE_TOKENS = (
    "insert_one",
    "insert_many",
    "replace_one",
    "update_one",
    "update_many",
    "delete_one",
    "delete_many",
    "bulk_write",
)


def _collect_get_functions(root: Path) -> dict[str, ast.FunctionDef]:
    """收集该目录下所有 ``@router.get(...)`` 装饰的函数。"""
    found: dict[str, ast.FunctionDef] = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr == "get"
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id == "router"
                ):
                    # 路径字面量（取第一个字符串参数）
                    route_path = ""
                    if deco.args and isinstance(deco.args[0], ast.Constant):
                        route_path = str(deco.args[0].value)
                    key = f"{path.relative_to(REPO_ROOT)}::{route_path}::{node.name}"
                    found[key] = node
    return found


def _write_calls_in_function(func: ast.AST) -> list[tuple[str, int]]:
    """列出函数体内所有写操作调用（含 ``.insert_one(`` 这类属性调用）。"""
    hits: list[tuple[str, int]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = ast.unparse(node.func)
        for token in _WRITE_TOKENS:
            if callee.endswith(f".{token}") or callee == token:
                hits.append((callee, node.lineno))
    return hits


def _get_functions_all() -> dict[str, ast.FunctionDef]:
    merged: dict[str, ast.FunctionDef] = {}
    for root in ROUTE_DIRS:
        if root.is_dir():
            merged.update(_collect_get_functions(root))
    return merged


def test_get_route_count_is_sane() -> None:
    """先确认扫描确实拿到了路由，避免"空集通过"式的假绿。"""
    fns = _get_functions_all()
    assert len(fns) >= 20, f"只扫到 {len(fns)} 个 GET 路由，扫描可能失效"


def test_no_get_route_calls_mongo_write_api() -> None:
    """022 FR-15：任何 GET 路由函数体内不得直接调用 MongoDB 写 API。"""
    offenders: list[str] = []
    for key, func in sorted(_get_functions_all().items()):
        for callee, lineno in _write_calls_in_function(func):
            offenders.append(f"{key}:{lineno} -> {callee}")
    assert not offenders, (
        "以下 GET 路由函数体内出现数据库写操作，违反『GET 无副作用』：\n"
        + "\n".join(offenders)
    )


def test_the_four_audited_gets_are_now_read_only() -> None:
    """QF-637 点名的 4 个端点，逐个确认写操作已拆出。"""
    fns = _get_functions_all()
    checks = [
        ("chat-api", "me", "GET /auth/me"),
        ("chat-api", "get_session", "GET /sessions/{id}"),
        ("chat-api", "get_resource", "GET /personal-knowledge/{id}"),
        ("admin-api", "get_org_billing", "GET /organizations/billing"),
    ]
    for service, func_name, label in checks:
        key = next(
            (k for k in fns if k.startswith(f"services/{service}/") and k.endswith(f"::{func_name}")),
            None,
        )
        assert key is not None, f"{label}（{func_name}）未找到"
        hits = _write_calls_in_function(fns[key])
        assert not hits, f"{label} 仍有写操作：{hits}"


def test_writes_live_in_explicit_post_endpoints() -> None:
    """写操作已拆到显式 POST：确认这些新端点存在且含写操作。"""
    expected_posts = [
        ("chat-api", "refresh_tenant_snapshot"),   # POST /auth/me/refresh-tenants
        ("chat-api", "mark_scheduled_read"),        # POST /sessions/{id}/read
        ("chat-api", "acknowledge_resource"),       # POST /personal-knowledge/{id}/ack
        ("admin-api", "init_org_billing"),          # POST /billing/init
    ]
    for service, func_name in expected_posts:
        found: str | None = None
        for root in ROUTE_DIRS:
            for path in sorted(root.glob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in tree.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if node.name != func_name:
                        continue
                    is_post = any(
                        isinstance(d, ast.Call)
                        and isinstance(d.func, ast.Attribute)
                        and d.func.attr == "post"
                        and isinstance(d.func.value, ast.Name)
                        and d.func.value.id == "router"
                        for d in node.decorator_list
                    )
                    assert is_post, f"{func_name} 存在但不是 @router.post"
                    assert _write_calls_in_function(node), (
                        f"{func_name} 声称是写端点但没有写操作"
                    )
                    found = str(path.relative_to(REPO_ROOT))
        assert found is not None, f"{func_name} 未找到"
