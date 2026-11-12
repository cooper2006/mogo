"""058 T007 — ``uuid4().hex`` 扫描脚本的单测。

直接验证扫描器的分类逻辑（``CALL_RE`` 命中 + ``_is_allowed`` 判别），
并做一次文件系统级集成：对一个临时 in-scope 目录扫描，确认新增实体主键被标记。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "check_uuid_hex_usage", scripts_dir / "check_uuid_hex_usage.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scanner():
    return _load_module()


def test_call_re_matches_entity_primary_key(scanner) -> None:
    assert scanner.CALL_RE.search("x = uuid.uuid4().hex")
    assert scanner.CALL_RE.search("y = uuid4().hex")
    assert not scanner.CALL_RE.search("import uuid")


def test_is_allowed_entity_pk_is_violation(scanner) -> None:
    ok, reason = scanner._is_allowed("employee_id = uuid.uuid4().hex")
    assert ok is False
    assert "实体主键" in reason


def test_is_allowed_exempt_marker(scanner) -> None:
    ok, _ = scanner._is_allowed(
        "tok = uuid.uuid4().hex  # id-unification-hex32-exempt: JWT jti"
    )
    assert ok is True


def test_is_allowed_slice_short_id(scanner) -> None:
    ok, _ = scanner._is_allowed("sid = uuid.uuid4().hex[:10]")
    assert ok is True


def test_is_allowed_tracked_id(scanner) -> None:
    ok, _ = scanner._is_allowed("rid = uuid4().hex  # request_id")
    assert ok is True


def test_scan_flags_new_entity_pk_in_in_scope_dir(scanner, monkeypatch) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "services" / "admin-api" / "evil.py"
        target.parent.mkdir(parents=True)
        target.write_text("MY_ID = uuid.uuid4().hex\n", encoding="utf-8")
        monkeypatch.chdir(root)
        violations, _allowed = scanner.scan(".")
        assert any("evil.py" in v["file"] for v in violations)
