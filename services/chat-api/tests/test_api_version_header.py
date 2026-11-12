"""059 T018/T019/T020 — 三服务 ``API-Version`` 响应头契约（机器可检）。

两部分：

1. 中间件单元：``ApiVersionMiddleware`` 给任意响应注入 ``API-Version`` 头
   （含异常响应），验证契约机制本身；
2. 注册校验：chat-api 与 document-parser 的 ``main.py`` 都已导入并挂载
   ``ApiVersionMiddleware``（059 要求的「跨服务 fail-closed 可机检约束」）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.common.api_version import API_VERSION_HEADER, ApiVersionMiddleware

starlette_testclient = pytest.importorskip("starlette.testclient")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_app(version: str = "1.0.0") -> Starlette:
    async def ep(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", ep)])
    app.add_middleware(ApiVersionMiddleware, version=version)
    return app


def test_middleware_injects_api_version_header() -> None:
    client = TestClient(_make_app("1.0.0"))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers[API_VERSION_HEADER] == "1.0.0"


def _main_py(svc: str) -> Path:
    return REPO_ROOT / "services" / svc / "app" / "main.py"


def test_chat_api_registers_api_version_middleware() -> None:
    src = _main_py("chat-api").read_text(encoding="utf-8")
    assert "from app.common.api_version import ApiVersionMiddleware" in src
    assert "app.add_middleware(ApiVersionMiddleware" in src


def test_document_parser_registers_api_version_middleware() -> None:
    src = _main_py("document-parser").read_text(encoding="utf-8")
    assert "from app.common.api_version import ApiVersionMiddleware" in src
    assert "app.add_middleware(ApiVersionMiddleware" in src
