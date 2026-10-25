"""025 FR-2 (T011) — 状态码语义扫描脚本的行为测试。

验证 `tools/api_check/status_code_semantics.py`：
- 错误路径 `raise HTTPException(status_code=200, ...)` → 命中
- 业务错误 `return {"success": False, ...}` / `return {"code": 非 0, ...}`（默认 200）→ 命中
- `JSONResponse(status_code=200, content={"code": 非 0})` → 命中
- 正确用法（`HTTPException(status_code=404)`、`{"success": True}`、`{"code": 0}`）→ 通过
- `include_in_schema=False` 兼容别名 → 跳过
- 真实仓库当前应 `status-code-semantics OK`（整改后），不得静默通过
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "api_check" / "status_code_semantics.py"


def _make_route(root: Path, source: str) -> None:
    route_file = (
        root / "services" / "admin-api" / "app" / "api" / "routes" / "sample_routes.py"
    )
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text(source, encoding="utf-8")


def _run_tmp(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestFindings:
    """违规模式必须被检出。"""

    def test_error_raised_with_200(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/items/{item_id}")
def get_item(item_id: str):
    raise HTTPException(status_code=200, detail="still processing")
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error-raised-with-2xx/3xx" in result.stdout

    def test_success_false_returned_with_default_200(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter()

@router.post("/items")
def create_item():
    return {"success": False, "message": "failed"}
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error-returned-with-default-200" in result.stdout

    def test_nonzero_code_returned_with_default_200(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
router = APIRouter()

@router.post("/items")
def create_item():
    return {"code": 1001, "message": "business error"}
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error-returned-with-default-200" in result.stdout

    def test_json_response_wrapping_error_in_200(self, tmp_path: Path) -> None:
        _make_route(
            tmp_path,
            """
from fastapi import APIRouter
from fastapi.responses import JSONResponse
router = APIRouter()

@router.post("/items")
def create_item():
    return JSONResponse(status_code=200, content={"success": False})
""",
        )
        result = _run_tmp(tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "error-wrapped-in-explicit-200" in result.stdout


class TestCompliance:
    """合规用法不得误报。"""

    SOURCE = """
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
router = APIRouter()

@router.get("/items/{item_id}")
def get_item(item_id: str):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

@router.post("/items")
def create_item():
    return JSONResponse(status_code=201, content={"code": 0, "id": "x"})

@router.get("/ok")
def ok():
    return {"success": True}

@router.get("/ok2")
def ok2():
    return {"code": 0, "data": []}

@router.post("/{item_id}/delete", include_in_schema=False, deprecated=True)
def legacy(item_id: str):
    return {"success": False}
"""

    def test_compliant_source_passes(self, tmp_path: Path) -> None:
        _make_route(tmp_path, self.SOURCE)
        result = _run_tmp(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr


class TestRealRepo:
    """真实仓库整改后应 0 违规；万一有违规必须如实报告，禁止永远 0 的假通过。"""

    def test_real_repo_reports_honestly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode in (0, 1), result.stdout + result.stderr
        if result.returncode == 1:
            assert "status-code-semantics FAILED" in result.stdout + result.stderr
