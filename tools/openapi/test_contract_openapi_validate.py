"""T041 OpenAPI 校验脚本测试（FR-26, QF-255）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openapi.validate import (
    ARTIFACT_DIR,
    _builtin_lint,
    _is_error_status,
    check_service,
    main,
)

REPO = Path(__file__).resolve().parents[2]


def _op(path: str, oid: str, tags=None, error_desc: bool = True, response_content: bool = True) -> dict:
    responses = {
        "200": {
            "description": "ok",
            "content": {} if response_content else None,
        }
    }
    if error_desc:
        responses["404"] = {"description": "not found"}
    return {
        path: {
            "get": {
                "operationId": oid,
                "tags": tags or ["api"],
                "responses": responses,
            }
        }
    }


def _valid_spec() -> dict:
    paths = {}
    paths.update(_op("/a", "op_a"))
    paths.update(_op("/b", "op_b", error_desc=True))
    return {"openapi": "3.1.0", "info": {"title": "x", "version": "1.0.0"}, "paths": paths}


# ---------- _builtin_lint ----------


def test_lint_clean_spec() -> None:
    problems, warnings = _builtin_lint(_valid_spec())
    assert problems == []
    assert warnings == []


def test_lint_missing_title_and_version() -> None:
    spec = _valid_spec()
    spec["info"] = {}
    problems, _ = _builtin_lint(spec)
    assert any("L1: info.title 缺失" in p for p in problems)
    assert any("L1: info.version 缺失" in p for p in problems)


def test_lint_empty_paths() -> None:
    spec = _valid_spec()
    spec["paths"] = {}
    problems, _ = _builtin_lint(spec)
    assert any("L2: paths 为空" in p for p in problems)


def test_lint_duplicate_operation_id() -> None:
    spec = _valid_spec()
    spec["paths"].update(_op("/c", "op_a"))  # 与 /a 的 op_a 重复
    problems, _ = _builtin_lint(spec)
    assert any("op_a' 重复" in p for p in problems)


def test_lint_missing_operation_id() -> None:
    spec = _valid_spec()
    spec["paths"]["/d"] = {"get": {"tags": ["api"], "responses": {"200": {"description": "ok"}}}}
    problems, _ = _builtin_lint(spec)
    assert any("L3: GET /d 缺 operationId" in p for p in problems)


def test_lint_missing_tags_is_warning_not_blocking() -> None:
    spec = _valid_spec()
    spec["paths"]["/d"] = {
        "get": {
            "operationId": "op_d",
            "responses": {"200": {"description": "ok"}},
        }
    }
    problems, warnings = _builtin_lint(spec)
    assert problems == []
    assert any("L4: GET /d 无 tags" in w for w in warnings)


def test_lint_error_response_missing_description() -> None:
    spec = _valid_spec()
    spec["paths"]["/d"] = {
        "get": {
            "operationId": "op_d",
            "tags": ["api"],
            "responses": {"200": {"description": "ok"}, "404": {"content": {"application/json": {}}}},
        }
    }
    problems, _ = _builtin_lint(spec)
    assert any("L5: GET /d 错误响应 404 缺 description" in p for p in problems)


# ---------- _is_error_status ----------


@pytest.mark.parametrize(
    ("status", "expected"),
    [("400", True), ("500", True), ("200", False), ("3XX", False), ("default", False), ("abc", False)],
)
def test_is_error_status(status: str, expected: bool) -> None:
    assert _is_error_status(status) is expected


# ---------- check_service / main ----------


def test_check_service_missing_artifact(tmp_path) -> None:
    ok, report = check_service("admin-api", tmp_path)
    assert not ok
    assert any("artifact 不存在" in r for r in report)


def test_check_service_invalid_json(tmp_path) -> None:
    artifact = tmp_path / "admin-api-openapi.json"
    artifact.write_text("{ not json", encoding="utf-8")
    ok, report = check_service("admin-api", tmp_path)
    assert not ok
    assert any("非法 JSON" in r for r in report)


def test_check_service_real_artifact_passes() -> None:
    for svc in ("admin-api", "chat-api", "document-parser"):
        ok, report = check_service(svc)
        assert ok, f"{svc} 校验失败: {report}"
        assert any("openapi-spec-validator 通过" in r for r in report)


def test_main_all_zero() -> None:
    assert main(["--all", "--skip-spectral"]) == 0


def test_ruleset_file_exists() -> None:
    ruleset = ARTIFACT_DIR / ".spectral-ruleset.yaml"
    assert ruleset.exists()
    text = ruleset.read_text(encoding="utf-8")
    assert "spectral:oas" in text
