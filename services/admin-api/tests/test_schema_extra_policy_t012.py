"""025 QF-210 (T012) — 未知字段策略一致性检查行为测试。

验证 `tools/api_check/schema_extra_policy.py`：
- `extra='allow'`（v2 `model_config` 与 v1 `class Config` 两种写法）必被点名
- `extra='forbid'` / `extra='ignore'` 合规不误报
- 非 BaseModel 类不误报
- 严格命名模型（*Request）未 forbid：默认通过，`--strict` 下失败
- 真实仓库当前通过，且失败时必须输出 `schema-extra-policy FAILED`（禁止静默）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = "tools/api_check/schema_extra_policy.py"
REPO = Path(__file__).resolve().parents[3]


def _run(args: list[str]):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


@pytest.fixture()
def fixture_repo(tmp_path):
    """构造最小仓库骨架：services/admin-api/app/schemas/x.py。"""
    app_dir = tmp_path / "services" / "admin-api" / "app" / "schemas"
    app_dir.mkdir(parents=True)
    return tmp_path, app_dir


def _write_model(app_dir, code: str) -> None:
    (app_dir / "sample.py").write_text(code, encoding="utf-8")


class TestViolations:
    def test_allow_configdict_reported(self, fixture_repo) -> None:
        tmp_path, app_dir = fixture_repo
        _write_model(
            app_dir,
            'from pydantic import BaseModel, ConfigDict\n\n'
            'class Loose(BaseModel):\n'
            '    model_config = ConfigDict(extra="allow")\n',
        )
        result = _run(["--root", str(tmp_path)])
        assert result.returncode == 1
        assert "schema-extra-policy FAILED" in (result.stdout + result.stderr)
        assert "extra='allow'" in (result.stdout + result.stderr)
        assert "Loose" in (result.stdout + result.stderr)

    def test_allow_v1_class_config_reported(self, fixture_repo) -> None:
        tmp_path, app_dir = fixture_repo
        _write_model(
            app_dir,
            'from pydantic import BaseModel\n\n'
            'class Legacy(BaseModel):\n'
            '    class Config:\n'
            '        extra = "allow"\n',
        )
        result = _run(["--root", str(tmp_path)])
        assert result.returncode == 1
        assert "Legacy" in (result.stdout + result.stderr)


class TestCompliant:
    def test_forbid_and_ignore_pass(self, fixture_repo) -> None:
        tmp_path, app_dir = fixture_repo
        _write_model(
            app_dir,
            'from pydantic import BaseModel, ConfigDict\n\n'
            'class StrictIn(BaseModel):\n'
            '    model_config = ConfigDict(extra="forbid")\n\n'
            'class LooseIn(BaseModel):\n'
            '    model_config = ConfigDict(extra="ignore")\n',
        )
        result = _run(["--root", str(tmp_path)])
        assert result.returncode == 0

    def test_non_basemodel_class_not_reported(self, fixture_repo) -> None:
        tmp_path, app_dir = fixture_repo
        _write_model(
            app_dir,
            'class NotAPydantic:\n'
            '    extra = "allow"\n',
        )
        result = _run(["--root", str(tmp_path)])
        assert result.returncode == 0

    def test_strict_named_model_default_pass(self, fixture_repo) -> None:
        tmp_path, app_dir = fixture_repo
        _write_model(
            app_dir,
            'from pydantic import BaseModel\n\n'
            'class SkillUpdateRequest(BaseModel):\n'
            '    name: str\n',
        )
        result = _run(["--root", str(tmp_path)])
        assert result.returncode == 0
        result_strict = _run(["--root", str(tmp_path), "--strict"])
        assert result_strict.returncode == 1
        assert "SkillUpdateRequest" in (result_strict.stdout + result_strict.stderr)


class TestRealRepo:
    def test_repo_has_no_allow(self) -> None:
        result = _run([])
        assert result.returncode == 0
        assert "schema-extra-policy OK" in result.stdout

    def test_repo_strict_reports_only_with_evidence(self) -> None:
        # 禁止永远 0 的假通过：若失败必须带明细
        result = _run(["--strict"])
        if result.returncode == 1:
            assert "schema-extra-policy FAILED" in (result.stdout + result.stderr)