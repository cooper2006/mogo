"""025 T021 / T022 / T023 — 错误响应规范扫描脚本 + admin-api OpenAPI 集成测试。

覆盖：
- `tools/api_check/error_response_refs.py` 对**合成坏样例**报出四类违规：
  `[code]`（坏稳定错误码）、`[leak]`（内部信息泄漏）、`[auth-shape]`（401/403 区分资源存在性）。
- 扫描对**干净样例**通过（不误报；纯字符串 detail 只给 `[info]` 提示，不计违规）。
- 扫描脚本 CLI 的退出码语义（--root 指向合成仓库：违规→1，干净→0）。
- admin-api 真实 OpenAPI：`components.schemas` 含 `ErrorResponse` / `ErrorFieldDetail`，
  且 4xx/5xx 通用错误响应 `$ref` 到 `ErrorResponse`（通过 `app.openapi()` 与
  `TestClient(app).get("/openapi.json")` 两种方式验证）。

不连真实 Mongo/Redis：OpenAPI 部分直接调用 `app.openapi()` 或 TestClient 拿 `/openapi.json`，
不触发业务路由；`app.main` 的 `init_db()` 只创建 motor client，不做网络连接。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "api_check" / "error_response_refs.py"

_REGISTERED = (
    "api.not_found",
    "api.unauthorized",
    "api.validation_error",
    "api.conflict",
    "api.internal_error",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("error_response_refs", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # 先注册进 sys.modules，避免 dataclass 处理时查不到 __module__
    sys.modules.setdefault(spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


SCRIPT_MOD = _load_script()


def _make_errors_py(root: Path) -> None:
    """合成仓库里写一个最小的 errors.py，供 load_registry / load_enum_members 识别。"""
    target = root / "services" / "admin-api" / "app" / "core" / "errors.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["from enum import Enum", "", "class ApiErrorCode(str, Enum):"]
    for code in _REGISTERED:
        lines.append(f'    {code.split(".")[-1].upper()} = "{code}"')
    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")


def _make_route(root: Path, rel: str, source: str) -> Path:
    target = root / "services" / "admin-api" / "app" / "api" / "routes" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def _scan(root: Path) -> list:
    registry = SCRIPT_MOD.load_registry(root)
    members = SCRIPT_MOD.load_enum_members(root)
    return SCRIPT_MOD.scan_routes_tree(
        root / "services/admin-api/app/api/routes", registry, members, root
    )


# ── 合成坏样例：应报三类违规 ───────────────────────────────────────────────────────


class TestSyntheticBadSample:
    @pytest.fixture(autouse=True)
    def _repo(self, tmp_path: Path) -> Path:
        _make_errors_py(tmp_path)
        _make_route(
            tmp_path,
            "bad_routes.py",
            """from fastapi import HTTPException
from app.core.errors import ApiErrorCode


def bad_literal_code():
    # [code] 坏稳定错误码：不以 api. 开头
    raise HTTPException(
        status_code=404,
        detail={"code": "CUSTOM_DUP", "message": "duplicate filename"},
    )


def unregistered_code():
    # [code] api. 前缀但未登记注册表
    raise HTTPException(
        status_code=409,
        detail={"code": "api.admin.unknown", "message": "unknown admin error"},
    )


def leak_internal_info():
    # [leak] detail/message 内出现绝对路径 + SQL + 内部模块 + 版本号
    raise HTTPException(
        status_code=500,
        detail={
            "code": "api.internal_error",
            "message": (
                "SELECT * FROM users WHERE id=1 crashed at "
                "/Users/cooper/app/routes/auth.py via app.core.engine v2.1.0"
            ),
        },
    )


def auth_notfound():
    # [auth-shape] 区分"用户不存在"
    raise HTTPException(
        status_code=401,
        detail={"code": "api.unauthorized", "message": "user not found"},
    )


def auth_password():
    # [auth-shape] 区分"密码错误"——与上一条并存即违规
    raise HTTPException(
        status_code=401,
        detail={"code": "api.unauthorized", "message": "password incorrect"},
    )
""",
        )
        return tmp_path

    def test_reports_code_violations(self, tmp_path: Path) -> None:
        issues = _scan(tmp_path)
        codes = [i for i in issues if i.category == "code"]
        text = "\n".join(i.render() for i in codes)
        assert any("CUSTOM_DUP" in t for t in (i.message for i in codes))
        assert any("api.admin.unknown" in i.message for i in codes)
        assert len(codes) == 2, text

    def test_reports_leak_violation(self, tmp_path: Path) -> None:
        issues = _scan(tmp_path)
        leaks = [i for i in issues if i.category == "leak"]
        assert leaks, "应报出 [leak] 违规"
        # message 串同时命中多种模式（SQL/绝对路径/模块名/版本号）→ 至少 1 条
        assert any("内部模块名" in i.message or "SQL" in i.message or "绝对文件路径" in i.message
                   or "版本号" in i.message for i in leaks)

    def test_reports_auth_shape_violation(self, tmp_path: Path) -> None:
        issues = _scan(tmp_path)
        shapes = [i for i in issues if i.category == "auth-shape"]
        assert len(shapes) == 1, f"应恰报 1 条 [auth-shape]：{shapes}"


# ── 合成干净样例：应通过 ───────────────────────────────────────────────────────────


class TestSyntheticCleanSample:
    @pytest.fixture(autouse=True)
    def _repo(self, tmp_path: Path) -> Path:
        _make_errors_py(tmp_path)
        _make_route(
            tmp_path,
            "clean_routes.py",
            """from fastapi import HTTPException
from app.core.errors import ApiErrorCode


def registered_literal():
    raise HTTPException(
        status_code=404,
        detail={"code": "api.not_found", "message": "resource not found"},
    )


def enum_value_access():
    raise HTTPException(
        status_code=422,
        detail={"code": ApiErrorCode.VALIDATION_ERROR.value, "message": "validation failed"},
    )


def plain_string_detail():
    # 兼容层允许：纯字符串 detail 只给 [info] 提示，不算违规
    raise HTTPException(status_code=400, detail="plain string, no code")


def auth_unified():
    # 只有一条统一 401 文案 → 不算 auth-shape
    raise HTTPException(
        status_code=401,
        detail={"code": "api.unauthorized", "message": "Invalid username or password"},
    )
""",
        )
        return tmp_path

    def test_clean_passes(self, tmp_path: Path) -> None:
        issues = _scan(tmp_path)
        violations = [i for i in issues if i.category not in ("info", "parse")]
        assert violations == [], f"干净样例不应报违规：{violations}"
        infos = [i for i in issues if i.category == "info"]
        # 纯字符串 detail 应作为提示出现（体现兼容层口径）
        assert any("纯字符串" in i.message for i in infos), infos


# ── CLI 退出码语义 ────────────────────────────────────────────────────────────────


class TestCliExitCode:
    def _run(self, root: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *extra],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_bad_root_exits_one(self, tmp_path: Path) -> None:
        _make_errors_py(tmp_path)
        _make_route(
            tmp_path,
            "bad_routes.py",
            'from fastapi import HTTPException\n\ndef a():\n'
            '    raise HTTPException(status_code=404, '
            'detail={"code": "CUSTOM_DUP", "message": "dup"})\n',
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "[code]" in result.stdout

    def test_clean_root_exits_zero(self, tmp_path: Path) -> None:
        _make_errors_py(tmp_path)
        _make_route(
            tmp_path,
            "clean_routes.py",
            'from fastapi import HTTPException\n\ndef a():\n'
            '    raise HTTPException(status_code=404, '
            'detail={"code": "api.not_found", "message": "missing"})\n',
        )
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stdout


# ── OpenAPI 集成（仅 admin-api）──────────────────────────────────────────────────


def test_patch_openapi_error_schema_on_bare_app() -> None:
    """直接调用定制函数：裸 FastAPI 上应暴露 ErrorResponse 并把 4xx/5xx 引用到它。"""
    from app.main import patch_openapi_error_schema  # noqa: E402

    app = FastAPI(title="mini", version="0.0.1")

    @app.get("/things")
    def list_things() -> dict:
        return {}

    patch_openapi_error_schema(app)
    schema = app.openapi()
    schemas = schema["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "ErrorFieldDetail" in schemas
    get_resp = schema["paths"]["/things"]["get"]["responses"]
    assert get_resp["422"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ErrorResponse"
    )
    assert get_resp["500"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ErrorResponse"
    )


def _count_error_response_refs(schema: dict) -> int:
    refs = 0
    for path_item in schema.get("paths", {}).values():
        for method in path_item.values():
            if not isinstance(method, dict):
                continue
            for resp in method.get("responses", {}).values():
                for ct in resp.get("content", {}).values():
                    if ct.get("schema", {}).get("$ref", "").endswith("ErrorResponse"):
                        refs += 1
    return refs


class TestRealAdminOpenApi:
    """验证 admin-api 真实 OpenAPI（不连 Mongo/Redis，仅取 schema）。"""

    def test_components_schemas_expose_error_response(self) -> None:
        from app.main import app  # noqa: E402

        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        assert "ErrorResponse" in schemas, "components.schemas 应暴露 ErrorResponse"
        assert "ErrorFieldDetail" in schemas
        assert schema["paths"], "OpenAPI 应有业务路径"
        assert _count_error_response_refs(schema) > 0, "4xx/5xx 响应应引用 ErrorResponse"

    def test_openapi_json_via_testclient(self) -> None:
        from app.core.config import settings  # noqa: E402
        from app.main import app  # noqa: E402

        # 生产环境（app_env=production/prod/release）main.py 显式关闭 docs/redoc/openapi
        # (openapi_url=None)；测试目标是 schema 内容（含 ErrorResponse 引用），
        # 与 app_env 无关。app_env=production 时直接调 app.openapi() 验证，不走 /openapi.json。
        is_prod = str(settings.app_env).strip().lower() in {"production", "prod", "release"}
        if is_prod:
            schema = app.openapi()
            assert "ErrorResponse" in schema["components"]["schemas"]
            assert _count_error_response_refs(schema) > 0
            return
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "ErrorResponse" in data["components"]["schemas"]
        assert _count_error_response_refs(data) > 0


# ── 真实仓库现状（只读防御，防脚本自身报错）────────────────────────────────────────


def test_real_repo_scan_runs_without_parse_errors() -> None:
    """在真实仓库上跑扫描：不应出现解析类错误（脚本对真实代码应可稳定工作）。"""
    if not (REPO_ROOT / "services/admin-api/app/api/routes").exists():
        pytest.skip("真实仓库不可用")
    registry = SCRIPT_MOD.load_registry(REPO_ROOT)
    members = SCRIPT_MOD.load_enum_members(REPO_ROOT)
    issues = SCRIPT_MOD.scan_routes_tree(
        REPO_ROOT / "services/admin-api/app/api/routes", registry, members, REPO_ROOT
    )
    assert not [i for i in issues if i.category == "parse"], issues