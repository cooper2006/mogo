"""Feature 034 - chat-api 侧凭证注入测试.

覆盖：
- ``_mcp_jsonrpc`` / ``_resolve_http_request`` 注入前对凭证字段解密；
- 身份头（runtime_headers）最后应用，不能被工具配置伪造；
- 解密失败 fail-closed（抛 EncryptionError，不出站）；
- ``_serialize`` 响应掩码 + LLM 侧描述符不透出明文凭证；
- ``test`` / ``test_draft`` 日志不含凭证明文。

与 admin-api 同源：加密/解密逻辑在 ``app/security/tool_credentials.py``。
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.security import kms
from app.security.encryption import EncryptionError, encrypt_value
from app.security.tool_credentials import CREDENTIAL_PURPOSE, reset_tool_credential_kms_cache
from app.services import external_tools

MASTER_KEY = b"unit-test-master-key-1234567890"
ENV_KEY = kms.MASTER_KEY_ENV


@pytest.fixture(autouse=True)
def _kms_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ENV_KEY, MASTER_KEY.decode())
    reset_tool_credential_kms_cache()
    yield
    reset_tool_credential_kms_cache()


def _kms():
    return kms.EnvVarKmsProvider(env={ENV_KEY: MASTER_KEY.decode()})


def _sealed(value: str) -> str:
    return encrypt_value(value, _kms(), purpose=CREDENTIAL_PURPOSE)


def _corrupt_blob(value: str) -> str:
    """生成 tag 已损坏的密文（仍是合法 blob 形态，GCM 校验失败）。"""
    blob = _sealed(value)
    return blob[:-2] + ("AA" if not blob.endswith("AA") else "BB")


class _CapturedClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def call(self, method, params):
        self.kwargs["method"] = method
        self.kwargs["params"] = params
        return {"content": [{"type": "text", "text": "ok"}]}


def test_mcp_jsonrpc_injects_decrypted_bearer(monkeypatch):
    captured = {}

    class FakeClient(_CapturedClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.update(kwargs)

    monkeypatch.setattr(external_tools, "StreamableHttpMcpClient", FakeClient)
    tool = {
        "config": {
            "endpoint": "https://mcp.example.test/mcp",
            "authType": "bearer",
            "authToken": _sealed("decrypted-token"),
        }
    }
    asyncio.run(
        external_tools.ExternalToolService()._mcp_jsonrpc(tool, "tools/list", {}),
    )
    assert captured["headers"]["Authorization"] == "Bearer decrypted-token"


def test_mcp_jsonrpc_injects_decrypted_api_key(monkeypatch):
    captured = {}

    class FakeClient(_CapturedClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.update(kwargs)

    monkeypatch.setattr(external_tools, "StreamableHttpMcpClient", FakeClient)
    tool = {
        "config": {
            "endpoint": "https://mcp.example.test/mcp",
            "authType": "api_key",
            "apiKeyHeader": "X-Key",
            "authToken": _sealed("key-value"),
        }
    }
    asyncio.run(external_tools.ExternalToolService()._mcp_jsonrpc(tool, "tools/list", {}))
    assert captured["headers"]["X-Key"] == "key-value"


def test_runtime_identity_headers_override_configured_headers(monkeypatch):
    captured = {}

    class FakeClient(_CapturedClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.update(kwargs)

    monkeypatch.setattr(external_tools, "StreamableHttpMcpClient", FakeClient)
    tool = {
        "config": {
            "endpoint": "https://mcp.example.test/mcp",
            "headers": {
                "X-MOGO-User-ID": "spoofed",
                "X-AskAI-User-ID": "spoofed",
                "secret": _sealed("header-secret"),
            },
        }
    }
    asyncio.run(
        external_tools.ExternalToolService()._mcp_jsonrpc(
            tool,
            "tools/list",
            {},
            runtime_headers={"X-MOGO-User-ID": "actor-1", "X-AskAI-User-ID": "actor-1"},
        )
    )
    # 身份头不可被工具配置伪造。
    assert captured["headers"]["X-MOGO-User-ID"] == "actor-1"
    assert captured["headers"]["X-AskAI-User-ID"] == "actor-1"
    # config.headers 内命中的凭证键在注入前已解密。
    assert captured["headers"]["secret"] == "header-secret"


def test_mcp_jsonrpc_fails_closed_on_corrupt_ciphertext(monkeypatch):
    class NeverCalledClient(_CapturedClient):
        def __init__(self, **kwargs):
            raise AssertionError("should not reach transport on decrypt failure")

    monkeypatch.setattr(external_tools, "StreamableHttpMcpClient", NeverCalledClient)
    tool = {
        "config": {
            "endpoint": "https://mcp.example.test/mcp",
            "authType": "bearer",
            "authToken": _corrupt_blob("token"),
        }
    }
    with pytest.raises(EncryptionError):
        asyncio.run(external_tools.ExternalToolService()._mcp_jsonrpc(tool, "tools/list", {}))


def test_http_resolver_injects_decrypted_token(monkeypatch):
    captured = {}

    async def fake_http_direct(resolved):
        captured.update(resolved)
        return {"success": True, "status": "passed", "message": "ok", "raw": {}}

    service = external_tools.ExternalToolService()
    monkeypatch.setattr(service, "_test_http_direct", fake_http_direct)
    tool = {
        "name": "t",
        "config": {
            "url": "https://api.example.test/v1",
            "method": "GET",
            "authType": "bearer",
            "authToken": _sealed("http-secret"),
        },
    }
    result = asyncio.run(service._test_http(tool, {}))
    assert result["success"] is True
    assert captured["headers"]["Authorization"] == "Bearer http-secret"


def test_serialize_redacts_credentials_and_never_exposes_plaintext():
    doc = {
        "_id": "d1",
        "name": "n",
        "type": "http",
        "config": {"authToken": "sk-visible-secret", "url": "https://x"},
    }
    out = external_tools._serialize(doc)
    assert out["config"]["authToken"] == "***"
    assert out["config"]["url"] == "https://x"
    assert "sk-visible-secret" not in repr(out)


def test_descriptors_do_not_expose_plaintext_to_llm(monkeypatch):
    sealed_config = {"authToken": _sealed("llm-must-not-see"), "url": "https://x"}

    async def fake_list_visible(*args, **kwargs):
        return [external_tools._serialize({"_id": "d1", "name": "t", "type": "http", "config": sealed_config})]

    monkeypatch.setattr(external_tools.ExternalToolService, "list_visible", fake_list_visible)
    descriptors = asyncio.run(external_tools.ExternalToolRegistry().list_enabled_descriptors())
    assert descriptors[0]["config"]["authToken"] == "***"
    assert "llm-must-not-see" not in repr(descriptors)


def test_test_path_logs_do_not_contain_plaintext_credentials(monkeypatch, caplog):
    # 走 test() 的日志路径：config 已被 _serialize 掩码，日志不含明文 token。
    sealed_config = {"authToken": _sealed("log-secret"), "url": "https://x"}

    async def fake_raw_get(*args, **kwargs):
        return {"_id": "t1", "name": "t", "type": "http", "config": sealed_config}

    async def fake_test_http(*args, **kwargs):
        return {"success": True, "status": "passed", "message": "ok", "raw": {}}

    async def fake_record_test(*args, **kwargs):
        return None

    monkeypatch.setattr(external_tools.ExternalToolService, "_raw_get", fake_raw_get)
    monkeypatch.setattr(external_tools.ExternalToolService, "_test_http", fake_test_http)
    monkeypatch.setattr(external_tools.ExternalToolService, "_record_test", fake_record_test)
    with caplog.at_level(logging.INFO, logger="app.external_tools"):
        asyncio.run(external_tools.ExternalToolService().test("t1", {}))
    assert "log-secret" not in caplog.text


def test_draft_test_logs_redact_credentials(caplog):
    payload = {"name": "draft", "type": "http", "config": {"authToken": "draft-secret", "url": "https://x"}}

    async def fake_test_http(*args, **kwargs):
        return {"success": True, "status": "passed", "message": "ok", "raw": {}}

    service = external_tools.ExternalToolService()
    original = service._test_http
    service._test_http = fake_test_http
    try:
        with caplog.at_level(logging.INFO, logger="app.external_tools"):
            asyncio.run(service.test_draft(payload, {}))
        assert "draft-secret" not in caplog.text
    finally:
        service._test_http = original


def test_decrypt_failure_surfaces_readable_error(monkeypatch):
    # 与 fail-closed 同义：解密异常向外抛，调用方返回可读错误而非回退明文。
    class BoomClient:
        def __init__(self, **kwargs):
            raise AssertionError("should not construct transport")

    monkeypatch.setattr(external_tools, "StreamableHttpMcpClient", BoomClient)
    tool = {"config": {"endpoint": "https://x", "authToken": _corrupt_blob("token")}}
    with pytest.raises(EncryptionError):
        asyncio.run(external_tools.ExternalToolService()._mcp_jsonrpc(tool, "tools/list", {}))