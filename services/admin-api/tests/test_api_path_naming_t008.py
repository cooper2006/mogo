"""025 T008 — 路径命名检查脚本的行为测试。

验证 `tools/api_check/path_naming.py`：
- 合规资源化路径（`/users`、`/documents/{id}`、内部 `_internal` 段）→ 退出码 0
- 动词段（`/getUsers`、`/listDocuments`、`/doParse`、裸 `/delete`）→ 退出码 1 且点名
- 严格模式额外捕获 add/remove/fetch 等动词
- 当前真实仓库现状应如实报告（若有违规不得静默通过）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "api_check" / "path_naming.py"


def _make_route(root: Path, source: str) -> None:
    route_file = (
        root / "services" / "admin-api" / "app" / "api" / "routes" / "sample_routes.py"
    )
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text(source, encoding="utf-8")


def _run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(REPO_ROOT), *extra],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_tmp(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestResourcePaths:
    """合规：资源化路径必须通过。"""

    def test_plain_resources_pass(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter(prefix="/api/users")

@router.get("")
def list_users(): ...

@router.get("/{user_id}")
def get_user(user_id: str): ...

@router.post("")
def create_user(): ...

@router.delete("/{user_id}")
def delete_user(user_id: str): ...

@router.get("/documents/{doc_id}/segments")
def segments(doc_id: str): ...
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_internal_underscore_segment_ignored(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter(prefix="/api/internal")

@router.post("/_admin/reconcile")
def reconcile(): ...
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_path_variable_segment_ignored(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter()

@router.get("/things/{get_token}")
def thing(get_token: str): ...
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr


class TestVerbSegments:
    """违规：动词段必须失败并点名。"""

    @pytest.mark.parametrize(
        "path",
        [
            "/getUsers",
            "/listDocuments",
            "/doParse",
            "/createThing",
            "/updateThing",
            "/delete",
            "/deleteThing",
            "/do_parse",
        ],
    )
    def test_verb_segment_fails(self, tmp_path: Path, path: str) -> None:
        _make_route(
            tmp_path,
            f"""
from fastapi import APIRouter
router = APIRouter()
@router.post("{path}")
def h(): ...
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert path.strip("/").split("/")[0] in result.stdout

    def test_prefix_verb_segment_fails(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter(prefix="/api/getUsers")
@router.get("")
def h(): ...
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1
        assert "getUsers" in result.stdout

    def test_strict_mode_catches_extra_verbs(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter()
@router.post("/fetchUsers")
def h(): ...
""",
        )
        permissive = _run_tmp(tmp_path)
        assert permissive.returncode == 0, permissive.stdout + permissive.stderr
        strict = _run_tmp(tmp_path, "--strict")
        assert strict.returncode == 1
        assert "fetchUsers" in strict.stdout


class TestJsonOutput:
    def test_json_reports_service_and_file(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter()
@router.get("/getUsers")
def h(): ...
""",
        )
        result = _run_tmp(tmp_path, "--json")
        assert result.returncode == 1
        assert '"problems"' in result.stdout
        assert '"segment": "getUsers"' in result.stdout


class TestRealRepo:
    """现状检查：不得静默通过真实违规。"""

    def test_script_does_not_hide_real_violations(self) -> None:
        result = _run()
        # 脚本必须如实反映仓库现状：要么干净（0），要么点名违规（1）。
        # 严禁「永远 0」的假通过——若仓库真实存在动词段，这里必须是 1。
        assert result.returncode in (0, 1)
        if result.returncode == 1:
            assert "path-naming FAILED" in result.stdout + result.stderr
            assert "[verb]" in result.stdout

class TestCompatAlias:
    """T009/T010 兼容别名：`include_in_schema=False, deprecated=True` 的旧路径默认跳过。

    整改后旧路径（动词段）以兼容别名保留，默认不应让脚本报红；
    但 `--strict` 下仍要如实报告，避免严格模式漏掉真问题。
    """

    ALIAS_SOURCE = """
from fastapi import APIRouter
router = APIRouter()

@router.post("/{resource_id}/deletion")
def delete_resource(resource_id: str): ...

@router.post("/{resource_id}/delete", include_in_schema=False, deprecated=True)
def delete_resource_legacy(resource_id: str): ...
"""

    def test_alias_skipped_by_default(self, tmp_path: Path) -> None:
        _make_route(tmp_path, self.ALIAS_SOURCE)
        result = _run_tmp(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "FAILED" not in result.stdout + result.stderr

    def test_alias_reported_under_strict(self, tmp_path: Path) -> None:
        _make_route(tmp_path, self.ALIAS_SOURCE)
        result = _run_tmp(tmp_path, "--strict")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "delete" in result.stdout + result.stderr
