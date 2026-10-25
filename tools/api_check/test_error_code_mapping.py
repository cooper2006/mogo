#!/usr/bin/env python3
"""T046 — 错误码映射稳定性检查工具（tools/api_check/error_code_mapping.py）的测试。

覆盖：首次生成基线、无漂移通过、状态码变更检测（changed_status_semantics）、
码被移除检测、字典与实现不一致（doc-drift / doc-orphan / undocumented）、
新增码向后兼容提示、--update-baseline 重建、未知服务报错、CLI 退出码。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from api_check import error_code_mapping as mapping  # noqa: E402


GOOD_ENUM = """
from enum import Enum

class ApiErrorCode(str, Enum):
    INTERNAL_ERROR = "api.internal_error"
    NOT_FOUND = "api.not_found"

DEFAULT_HTTP_STATUS = {
    "api.internal_error": 500,
    "api.not_found": 404,
}
"""

GOOD_DICT = """# 错误码字典（测试用）
## 2. 通用错误码字典
| `code` | `http_status` | `trigger` | `remedy` |
|---|---|---|---|
| `api.internal_error` | `500` | 未处理异常兜底 | 反馈 trace_id |
| `api.not_found` | `404` | 资源不存在 | 校验 ID |
"""


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enum_text: str = GOOD_ENUM,
    dict_text: str = GOOD_DICT,
    two_services: bool = False,
):
    """把 SERVICES 指到 tmp_path 下的假 errors.py，返回 (baseline, dict) 路径。"""
    ep = tmp_path / "errors.py"
    ep.write_text(enum_text, encoding="utf-8")
    services = {"admin-api": str(ep)}
    if two_services:
        ep2 = tmp_path / "errors2.py"
        ep2.write_text(enum_text, encoding="utf-8")
        services["chat-api"] = str(ep2)
    monkeypatch.setattr(mapping, "SERVICES", services)
    dp = tmp_path / "codes.md"
    dp.write_text(dict_text, encoding="utf-8")
    bp = tmp_path / "error-code-mapping.json"
    return bp, dp


def _run(bp, dp, extra=None):
    # 显式限定当前 SERVICES 里的服务（monkeypatch 场景下 SERVICES 可能只是子集）
    argv = [
        "--baseline",
        str(bp),
        "--dict",
        str(dp),
        "--services",
        ",".join(mapping.SERVICES),
    ]
    if extra:
        argv += extra
    return mapping.main(argv)


def test_first_run_creates_baseline_and_passes(tmp_path, monkeypatch):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    assert bp.exists()
    snap = json.loads(bp.read_text(encoding="utf-8"))
    assert snap["services"]["admin-api"]["api.internal_error"] == 500
    assert snap["services"]["admin-api"]["api.not_found"] == 404
    # 再次运行：无漂移
    assert _run(bp, dp) == 0


def test_status_change_detected_as_breaking(tmp_path, monkeypatch, capsys):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    changed = GOOD_ENUM.replace('"api.not_found": 404', '"api.not_found": 410')
    bp2, dp2 = _setup(tmp_path, monkeypatch, enum_text=changed)
    assert _run(bp2, dp2) == 1
    out = capsys.readouterr().out
    assert "changed_status_semantics" in out
    assert "404 -> 410" in out
    assert "major" in out


def test_removed_code_detected_as_breaking(tmp_path, monkeypatch, capsys):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    removed = GOOD_ENUM.replace('    NOT_FOUND = "api.not_found"\n', "")
    bp2, dp2 = _setup(tmp_path, monkeypatch, enum_text=removed)
    assert _run(bp2, dp2) == 1
    assert "已被移除" in capsys.readouterr().out


def test_added_code_is_compat_info(tmp_path, monkeypatch, capsys):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    added = GOOD_ENUM.replace(
        '    NOT_FOUND = "api.not_found"',
        '    NOT_FOUND = "api.not_found"\n    CONFLICT = "api.conflict"',
    ).replace(
        '    "api.not_found": 404,',
        '    "api.not_found": 404,\n    "api.conflict": 409,',
    )
    added_dict = GOOD_DICT + "| `api.conflict` | `409` | 冲突 | 处理冲突 |\n"
    bp2, dp2 = _setup(tmp_path, monkeypatch, enum_text=added, dict_text=added_dict)
    assert _run(bp2, dp2) == 0
    assert "新增错误码 api.conflict" in capsys.readouterr().out


def test_update_baseline_resets(tmp_path, monkeypatch):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    changed = GOOD_ENUM.replace('"api.not_found": 404', '"api.not_found": 410')
    changed_dict = GOOD_DICT.replace("`api.not_found` | `404`", "`api.not_found` | `410`")
    bp2, dp2 = _setup(tmp_path, monkeypatch, enum_text=changed, dict_text=changed_dict)
    assert _run(bp2, dp2, extra=["--update-baseline"]) == 0
    snap = json.loads(bp.read_text(encoding="utf-8"))
    assert snap["services"]["admin-api"]["api.not_found"] == 410
    # 重建后再跑应通过
    assert _run(bp2, dp2) == 0


def test_doc_mapping_inconsistent(tmp_path, monkeypatch, capsys):
    bp, dp = _setup(tmp_path, monkeypatch)
    assert _run(bp, dp) == 0
    bad_dict = GOOD_DICT.replace("`api.not_found` | `404`", "`api.not_found` | `400`")
    bp2, dp2 = _setup(tmp_path, monkeypatch, dict_text=bad_dict)
    assert _run(bp2, dp2) == 1
    assert "doc-drift" in capsys.readouterr().out


def test_doc_orphan_code(tmp_path, monkeypatch, capsys):
    _, dp = _setup(tmp_path, monkeypatch)
    extra_dict = GOOD_DICT + "| `api.conflict` | `409` | 冲突 | 处理冲突 |\n"
    bp2, dp2 = _setup(tmp_path, monkeypatch, dict_text=extra_dict)
    assert _run(bp2, dp2) == 1
    assert "doc-orphan" in capsys.readouterr().out


def test_undocumented_code(tmp_path, monkeypatch, capsys):
    _, dp = _setup(tmp_path, monkeypatch)
    # 实现里有 not_found，但字典只登记 internal_error
    slim_dict = GOOD_DICT.replace("| `api.not_found` | `404` | 资源不存在 | 校验 ID |\n", "")
    bp2, dp2 = _setup(tmp_path, monkeypatch, dict_text=slim_dict)
    assert _run(bp2, dp2) == 1
    assert "undocumented" in capsys.readouterr().out


def test_cross_service_status_drift(tmp_path, monkeypatch, capsys):
    bp, dp = _setup(tmp_path, monkeypatch, two_services=True)
    changed = GOOD_ENUM.replace('"api.not_found": 404', '"api.not_found": 410')
    # 第二个服务用不同状态
    ep2 = tmp_path / "errors2.py"
    ep2.write_text(changed, encoding="utf-8")
    monkeypatch.setattr(mapping, "SERVICES", {
        "admin-api": str(tmp_path / "errors.py"),
        "chat-api": str(ep2),
    })
    assert _run(bp, dp) == 1
    assert "跨服务状态不一致" in capsys.readouterr().out


def test_unknown_service_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit):
        mapping.main(["--services", "nope"])


def test_missing_errors_file_is_tolerated(tmp_path, monkeypatch):
    """errors.py 缺失时不 crash，按空映射处理。"""
    dp = tmp_path / "codes.md"
    dp.write_text(GOOD_DICT, encoding="utf-8")
    bp = tmp_path / "baseline.json"
    monkeypatch.setattr(mapping, "SERVICES", {"admin-api": str(tmp_path / "absent.py")})
    # 空实现 + 非空字典 → doc-orphan 报错
    assert _run(bp, dp) == 1


def test_parse_docs_dict_unit(tmp_path):
    p = tmp_path / "d.md"
    p.write_text(
        "| `code` | `http_status` | `trigger` | `remedy` |\n"
        "|---|---|---|---|\n"
        "| `api.internal_error` | `500` | x | y |\n"
        "| `api.rate_limited` | `429` | z | w |\n",
        encoding="utf-8",
    )
    assert mapping.parse_docs_dict(p) == {
        "api.internal_error": 500,
        "api.rate_limited": 429,
    }


def test_parse_errors_py_missing_file(tmp_path):
    assert mapping.parse_errors_py(tmp_path / "nope.py") == (set(), {})