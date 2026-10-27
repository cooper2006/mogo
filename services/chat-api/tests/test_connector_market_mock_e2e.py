"""041-connector-market 的 mock E2E 契约测试（T019 的本地可执行段）。

范围（诚实降级，见 spec.md 与 tasks.md T019 的验收注释）：
  - 模板 YAML -> render_config（本文件内按 admin-api ``app/services/connector_templates.py::render_config``
    的契约复现，避免跨包 import 造成 ``app`` 命名冲突）-> chat-api ``_resolve_http_request`` -> 真实 HTTP 打到
    本地 mock 上游，覆盖「模板 → 创建(落库) → 测试 → runtime 调用成功」。
  - 审计段（``enterprise_capabilities/tools/service.py::EnterpriseToolService.decide/execute``）依赖
    ToolGateway 全链路（RuntimeProfileStore + InternalCapabilityService + 审批），无法在本机单测内构造，
    由既有 ``tests/enterprise_capabilities/tools/`` 用例与 staging 联调覆盖；本文件用
    ``_build_debug_trace`` 验证可审计信息（resolvedUrl / headerKeys / hasBody）在调用后仍可解析。
  - 凭证仅服务端注入：mock 收到的 Authorization/PRIVATE-TOKEN 头来自 config，客户端 arguments 不携带。
"""

from __future__ import annotations

import http.server
import threading
from typing import Any
from urllib.parse import urlparse
from pathlib import Path

import pytest
import yaml

from app.services.external_tools import ExternalToolService

# 模板路径按宿主/容器双环境解析：宿主仓库根在 /Users/cooper/mogo（或本机 worktree），
# 容器内仓库挂 /mogo（-v <host>/mogo:/mogo:ro）。优先取当前仓库根（本测试文件所在目录
# 的上 2 级 = services/chat-api 的父目录 services/ → 再上 1 级 = 仓库根）。
_ADMIN_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "admin-api" / "app" / "connector_templates" / "gitlab-api.yaml"
)
ADMIN_TEMPLATE = str(_ADMIN_TEMPLATE)


class _MockHandler(http.server.BaseHTTPRequestHandler):
    seen: list[dict[str, Any]] = []

    def log_message(self, *args: Any) -> None:  # 静音
        return

    def _capture(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length).decode("utf-8") if length else ""
        record: dict[str, Any] = {
            "method": self.command,
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
        }
        _MockHandler.seen.append(record)
        payload = b'{"data":[{"id":1,"name":"proj"}],"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _capture
    do_POST = _capture


@pytest.fixture()
def mock_upstream() -> tuple[str, int]:
    """起本地 mock 上游，返回 (base_url_without_scheme, port)。"""
    _MockHandler.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_address[1]}", server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _render_config(mock_host: str, token: str = "tok-abc") -> dict[str, Any]:
    """按 041 render_config 契约把模板渲染为 chat-api 可消费的 config。"""
    with open(ADMIN_TEMPLATE, "r", encoding="utf-8") as fh:
        template = yaml.safe_load(fh)
    assert template["auth_type"] == "api_key"
    values = {"host": mock_host, "path": "projects", "token": token}
    url = str(template["config_template"]["url"])
    for key, value in values.items():
        url = url.replace("${" + key + "}", str(value))
    # 本地 mock 无 TLS：仅协议替换，不改变连接器契约（真实部署由模板 host 决定 https）。
    url = url.replace("https://", "http://", 1)
    config: dict[str, Any] = {
        "url": url,
        "method": str(template["config_template"]["method"]),
        "timeoutSeconds": 30,
        "executionMode": "direct_http",
        "authType": "api_key",
        "authToken": token,
        "apiKeyHeader": str(template.get("api_key_header") or "X-API-Key"),
        "inputSchema": [
            {"name": "project_id", "location": "Path", "type": "string", "required": False,
             "description": "GitLab project id"},
        ],
    }
    return config


def _tool(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": "tool-041-1",
        "tenant_id": "t1",
        "name": "GitLab API",
        "type": "http",
        "scope": "organization",
        "status": "active",
        "last_test_status": "untested",
        "config": config,
    }


class _UpdateResult:
    matched_count = 1
    modified_count = 1
    upserted_id = None


class _FakeTools:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    async def find_one(self, query: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return self._raw

    async def update_one(self, flt: Any, upd: Any, upsert: bool = False) -> _UpdateResult:  # noqa: ARG002
        return _UpdateResult()


class _FakeDb:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.external_tools = _FakeTools(raw)
        self._raw = raw

    def __getitem__(self, name: str) -> Any:
        if name == "external_tools":
            return self.external_tools
        return _FakeTools({})


@pytest.mark.asyncio
async def test_template_renders_config_resolvable_by_chat_api(mock_upstream) -> None:
    host, port = mock_upstream
    config = _render_config(host)
    service = ExternalToolService()
    tool = _tool(config)
    resolved = service._resolve_http_request(tool, {"query": {"per_page": "1"}, "path": {}, "headers": {}, "body": {}})
    assert resolved["method"] == "GET"
    assert "PRIVATE-TOKEN" in resolved["headers"]
    assert resolved["headers"]["PRIVATE-TOKEN"] == "tok-abc"
    # URL 渲染后不再含模板占位符，且指向本地 mock
    assert "${host}" not in resolved["url"]
    assert f"127.0.0.1:{port}" in resolved["url"]


@pytest.mark.asyncio
async def test_mock_upstream_receives_request_and_returns_ok(mock_upstream) -> None:
    host, _ = mock_upstream
    config = _render_config(host)
    service = ExternalToolService()
    resolved = service._resolve_http_request(_tool(config), {"query": {"per_page": "1"}, "path": {}, "headers": {}, "body": {}})
    result = await service._test_http_direct(resolved)
    assert result["success"] is True
    assert _MockHandler.seen, "mock upstream 应收到请求"
    record = _MockHandler.seen[-1]
    assert record["method"] == "GET"
    assert record["headers"].get("PRIVATE-TOKEN") == "tok-abc"
    assert urlparse(record["path"]).path == "/api/v4/projects"


@pytest.mark.asyncio
async def test_runtime_execute_http_hits_mock_and_keeps_audit_trace(mock_upstream, monkeypatch) -> None:
    host, _ = mock_upstream
    config = _render_config(host)
    # find_one 直接返回 raw；_execution_tool 内部走 decrypt_credentials（宽容解密，明文/密文双跑期均可）
    raw = _tool(config)
    db = _FakeDb(raw)
    monkeypatch.setattr("app.services.external_tools.get_db", lambda: db)
    service = ExternalToolService()
    result = await service.execute_runtime(
        tenant_id="t1",
        external_tool_id="tool-041-1",
        provider_type="http",
        arguments={"per_page": "1"},
    )
    assert result["success"] is True
    assert _MockHandler.seen, "runtime 调用应命中 mock 上游"
    record = _MockHandler.seen[-1]
    assert record["headers"].get("PRIVATE-TOKEN") == "tok-abc"
    assert "debug" in result
    assert result["debug"]["resolvedUrl"].startswith("http://127.0.0.1:")
    assert "PRIVATE-TOKEN" in result["debug"]["headerKeys"]
    assert result["debug"]["hasBody"] is False


@pytest.mark.asyncio
async def test_runtime_rejects_disabled_connector(mock_upstream, monkeypatch) -> None:
    host, _ = mock_upstream
    raw = _tool(_render_config(host))
    raw["status"] = "disabled"
    monkeypatch.setattr("app.services.external_tools.get_db", lambda: _FakeDb(raw))
    service = ExternalToolService()
    with pytest.raises(ValueError, match="工具连接未启用"):
        await service.execute_runtime(
            tenant_id="t1", external_tool_id="tool-041-1", provider_type="http", arguments={}
        )