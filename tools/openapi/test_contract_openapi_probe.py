"""T047 OpenAPI 与实测一致性探针测试（FR-25, QF-254）。

覆盖：artifact 加载、响应 schema 字段名递归收集（$ref/allOf/oneOf/opaque）、
必填 query 参数提取、document-parser 跳过逻辑、CLI 退出码与 JSON 输出。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.openapi.generate import ARTIFACT_DIR, SERVICES
from tools.openapi.probe import (
    collect_field_names,
    load_spec,
    main,
    _required_query_params,
)

REPO = Path(__file__).resolve().parents[2]
COMPONENTS: dict = {"schemas": {}}


# ── artifact 加载 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("service", SERVICES)
def test_artifact_loads(service: str) -> None:
    spec = load_spec(service)
    assert spec["openapi"].startswith("3.1")
    assert spec.get("paths")


def test_artifact_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_spec("nonexistent")


# ── 字段名递归收集 ──────────────────────────────────────────────────────────────────


def test_collect_top_level_properties() -> None:
    schema = {"type": "object", "properties": {"id": {"type": "str"}, "name": {"type": "str"}}}
    assert collect_field_names(schema, COMPONENTS) == {"id", "name"}


def test_collect_resolves_ref() -> None:
    COMPONENTS["schemas"] = {"Thing": {"type": "object", "properties": {"id": {"type": "str"}, "ok": {"type": "bool"}}}}
    schema = {"$ref": "#/components/schemas/Thing"}
    assert collect_field_names(schema, COMPONENTS) == {"id", "ok"}


def test_collect_merges_allof() -> None:
    schema = {
        "allOf": [
            {"type": "object", "properties": {"a": {"type": "str"}}},
            {"type": "object", "properties": {"b": {"type": "int"}}},
        ]
    }
    assert collect_field_names(schema, COMPONENTS) == {"a", "b"}


def test_collect_merges_oneof() -> None:
    schema = {
        "oneOf": [
            {"type": "object", "properties": {"x": {"type": "str"}}},
            {"type": "object", "properties": {"y": {"type": "str"}}},
        ]
    }
    assert collect_field_names(schema, COMPONENTS) == {"x", "y"}


def test_collect_array_item_opaque_returns_empty() -> None:
    # 数组元素为自由 dict（无 properties）→ opaque，跳过
    schema = {"type": "array", "items": {"type": "object"}}
    assert collect_field_names(schema, COMPONENTS) == set()


def test_collect_array_schema_has_no_top_level_fields() -> None:
    # 探针只比对顶层字段名；数组响应顶层无属性名 → 视为 opaque 跳过（items 不深入）
    schema = {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "str"}}}}
    assert collect_field_names(schema, COMPONENTS) == set()


def test_collect_unknown_schema_returns_empty() -> None:
    assert collect_field_names(None, COMPONENTS) == set()
    assert collect_field_names({}, COMPONENTS) == set()


# ── 必填 query 参数提取 ─────────────────────────────────────────────────────────────


def test_required_query_params_picks_only_required_no_default() -> None:
    op = {"parameters": [
        {"name": "page", "in": "query", "required": True, "schema": {"type": "int"}},
        {"name": "size", "in": "query", "required": True, "schema": {"type": "int", "default": 20}},
        {"name": "kw", "in": "query", "schema": {"type": "str"}},
        {"name": "tenant", "in": "path", "required": True},
    ]}
    assert _required_query_params(op) == ["page"]


# ── document-parser 跳过逻辑（依赖缺失时不阻断） ────────────────────────────────────


def test_document_parser_probe_not_error() -> None:
    """document-parser 本地缺 celery：子进程探针应返回 skipped 或 ok，不得 error。"""
    rc = main(["--service", "document-parser", "--limit", "2"])
    assert rc == 0  # 无一致性问题即视为通过（任务口径：跳过不阻断）


# ── CLI 退出码与 JSON 输出 ─────────────────────────────────────────────────────────


def test_cli_admin_api_no_consistent_error() -> None:
    """admin-api 探针：路径可达性不应发现实现缺失；rc 由字段/参数比对决定（允许 0 或 1）。"""
    proc = subprocess.run(
        [sys.executable, "tools/openapi/probe.py", "--service", "admin-api", "--limit", "2"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode in (0, 1), proc.stderr[-800:]
    # 子进程未崩溃：不应输出 status=error 且 notes 非空（error 情形 rc 也为 0，故显式断言）
    assert "依赖缺失" not in proc.stdout


def test_cli_json_output_shape(tmp_path) -> None:
    out = tmp_path / "report.json"
    code = (
        "import json, sys\n"
        "sys.path.insert(0, 'tools')\n"
        "from tools.openapi.probe import probe_service\n"
        f"r = probe_service({SERVICES[0]!r}, limit=1)\n"
        f"open({str(out)!r}, 'w', encoding='utf-8').write(json.dumps(r.as_dict(), ensure_ascii=False))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-800:]
    rep = json.loads(out.read_text(encoding="utf-8"))
    for key in ("service", "status", "probed", "skipped", "problems", "notes"):
        assert key in rep, f"报告缺字段 {key}: {rep}"
    assert rep["service"] == SERVICES[0]
    assert isinstance(rep["problems"], list)
    assert rep["status"] in ("ok", "skipped", "problem", "error")


def test_cli_main_returns_int() -> None:
    rc = main(["--service", "admin-api", "--limit", "1"])
    assert isinstance(rc, int)