"""057：``GET /api/v1/admin/compatibility/pipeline-support`` 端点 call_sites 一致性。

此前验收项「端点返回正确 JSON、call_sites 与实际扫描一致」因端点内部硬编码
``find_aggregate_calls("/app")``（容器内代码根）、本地无 ``/app`` 挂载而无法实机
验证，保持 ``[ ]``。本文件补齐实证：

- 用 mini FastAPI app 挂载 ``compatibility.api_router``，override admin 依赖，
  避免依赖真实数据库/容器路径。
- monkeypatch ``app.core.pg_compat_scan.find_aggregate_calls``，使端点扫描一个
  **本地临时目录**（含违规 ``$unwind`` 文件与合规 ``$match`` 文件），而非 ``/app``。
- 断言响应 JSON 的 ``call_sites``（file/line/stages/status）与真实扫描结果一致、
  ``summary`` 统计正确、``supported_stages`` 与常量一致。

不依赖 tmp_path 夹具（WorkBuddy shim 下会 FileExistsError），用
``tempfile.TemporaryDirectory()`` 手动管理。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import compatibility
from app.core import pg_compat_scan
from app.core.pg_compat import SUPPORTED_AGGREGATION_STAGES


def _write(tmp: str, rel: str, text: str) -> Path:
    p = Path(tmp) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _build_client() -> TestClient:
    """mini app：只挂 057 兼容性路由，override admin 鉴权（不连数据库）。"""
    app = FastAPI()
    app.include_router(compatibility.api_router)
    app.dependency_overrides[deps.get_current_admin_user] = lambda: {
        "tenant_id": "t_admin",
        "username": "qa",
    }
    return TestClient(app)


def test_pipeline_support_call_sites_match_real_scan(monkeypatch) -> None:
    """call_sites 必须与真实扫描结果一致（status 判定正确）。"""
    # 在 monkeypatch 前保存原始函数引用，避免 lambda 内再次调用被替换的模块属性
    # 导致无限递归。
    real_fn = pg_compat_scan.find_aggregate_calls

    with tempfile.TemporaryDirectory() as tmp:
        # 违规文件：$unwind（不在 SUPPORTED 内）
        _write(
            tmp,
            "svc_a/bad.py",
            "from db import coll\n"
            "async def f():\n"
            "    return await coll.aggregate([{\"$unwind\": \"$items\"}])\n",
        )
        # 合规文件：$match（在 SUPPORTED 内）
        _write(
            tmp,
            "svc_b/good.py",
            "from db import coll\n"
            "async def f():\n"
            "    return await coll.aggregate([{\"$match\": {\"active\": True}}])\n",
        )
        # 不相关文件：无 aggregate 调用
        _write(tmp, "svc_c/plain.py", "x = 1\n")

        real = real_fn(tmp)
        # 预检：临时目录里的确扫出 1 处 $unwind 违规
        assert len(real) == 1
        assert real[0]["stage"] == "unwind"

        monkeypatch.setattr(
            "app.core.pg_compat_scan.find_aggregate_calls",
            lambda root_dir, staged=False: real_fn(tmp),
        )

        resp = _build_client().get("/admin/compatibility/pipeline-support")
        assert resp.status_code == 200, resp.text

        body = resp.json()
        # supported_stages 与常量一致（排序）
        assert body["supported_stages"] == sorted(SUPPORTED_AGGREGATION_STAGES)

        # call_sites 与真实扫描逐项一致
        assert len(body["call_sites"]) == len(real)
        for cs, v in zip(body["call_sites"], real):
            assert cs["file"].endswith(v["file"])
            assert cs["line"] == v["line"]
            assert v["stage"] in cs["stages"]
            expected_status = (
                "has_unsupported_stage"
                if v["stage"] not in SUPPORTED_AGGREGATION_STAGES
                else "fully_supported"
            )
            assert cs["status"] == expected_status

        # summary 统计
        assert body["summary"]["total_calls"] == len(real)
        assert body["summary"]["fully_supported"] == sum(
            1 for v in real if v["stage"] in SUPPORTED_AGGREGATION_STAGES
        )
        assert body["summary"]["has_unsupported_stage"] == sum(
            1 for v in real if v["stage"] not in SUPPORTED_AGGREGATION_STAGES
        )


def test_pipeline_support_rejects_unauthenticated(monkeypatch) -> None:
    """无 admin 依赖时端点被 401/403 拒绝（RBAC 守卫生效）。"""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(
            "app.core.pg_compat_scan.find_aggregate_calls",
            lambda root_dir, staged=False: [],
        )
        # 不 override 依赖：get_current_admin_user 需要 authorization header，
        # 缺失时应被拒绝，而不是被静默放行。
        app = FastAPI()
        app.include_router(compatibility.api_router)
        resp = TestClient(app).get("/admin/compatibility/pipeline-support")
        assert resp.status_code in (401, 403), resp.status_code
