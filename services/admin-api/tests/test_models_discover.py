from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import models as models_route


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _mount_app() -> TestClient:
    app = FastAPI()
    app.include_router(models_route.router)
    app.dependency_overrides[models_route.get_current_admin_user] = lambda: {"tenant_id": "default"}
    return TestClient(app)


def test_discover_openai_compatible_parses_models(monkeypatch) -> None:
    fake = _FakeResponse(
        {
            "object": "list",
            "data": [
                {"id": "gpt-4o", "owned_by": "openai"},
                {"id": "gpt-4o-mini", "owned_by": "openai"},
                {"id": "gpt-4o", "owned_by": "openai"},  # 重复，应去重
            ],
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)
    result = models_route._discover_openai_compatible_models("https://api.openai.com/v1/", "sk-test")
    assert [item["id"] for item in result] == ["gpt-4o", "gpt-4o-mini"]
    assert result[0]["ownedBy"] == "openai"


def test_discover_azure_parses_deployments(monkeypatch) -> None:
    fake = _FakeResponse(
        {
            "data": [
                {"id": "gpt-4o-prod", "display_name": "GPT-4o Production"},
                {"id": "gpt-4o-mini-prod"},
            ]
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)
    result = models_route._discover_azure_models("https://example.openai.azure.com/", "key", "2024-10-21")
    assert [item["id"] for item in result] == ["gpt-4o-prod", "gpt-4o-mini-prod"]
    assert result[0]["name"] == "GPT-4o Production"


def test_discover_openai_compatible_surfaces_http_error(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={"providerType": "openai_compatible", "baseUrl": "https://api.openai.com/v1", "apiKey": "bad"},
    )
    assert resp.status_code == 502
    assert "HTTP 401" in resp.json()["detail"]


def test_discover_route_returns_models(monkeypatch) -> None:
    client = _mount_app()
    monkeypatch.setattr(
        models_route,
        "_discover_openai_compatible_models",
        lambda base_url, api_key: [{"id": "gpt-4o", "name": "gpt-4o", "ownedBy": "openai"}],
    )
    resp = client.post(
        "/discover",
        json={"providerType": "openai_compatible", "baseUrl": "https://api.openai.com/v1", "apiKey": "sk"},
    )
    assert resp.status_code == 200
    assert resp.json()["models"][0]["id"] == "gpt-4o"


def test_discover_rejects_unknown_provider_type(monkeypatch) -> None:
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={"providerType": "foo", "baseUrl": "https://example.com", "apiKey": "k"},
    )
    assert resp.status_code == 422


def test_discover_anthropic_parses_models(monkeypatch) -> None:
    fake = _FakeResponse(
        {
            "data": [
                {"id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet"},
                {"id": "claude-3-5-haiku-20241022"},
            ]
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)
    result = models_route._discover_anthropic_models("https://api.anthropic.com", "sk-test")
    assert [item["id"] for item in result] == ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
    assert result[0]["ownedBy"] == "anthropic"


def test_discover_gemini_strips_models_prefix(monkeypatch) -> None:
    fake = _FakeResponse(
        {
            "models": [
                {"name": "models/gemini-1.5-pro", "displayName": "Gemini 1.5 Pro"},
                {"name": "models/gemini-1.5-flash"},
            ]
        }
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)
    result = models_route._discover_gemini_models("https://generativelanguage.googleapis.com", "key")
    assert [item["id"] for item in result] == ["gemini-1.5-pro", "gemini-1.5-flash"]
    assert result[0]["name"] == "Gemini 1.5 Pro"


def test_discover_ollama_parses_models(monkeypatch) -> None:
    fake = _FakeResponse({"models": [{"name": "llama3.1"}, {"name": "qwen2.5:7b"}]})
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: fake)
    result = models_route._discover_ollama_models("http://localhost:11434", "")
    assert [item["id"] for item in result] == ["llama3.1", "qwen2.5:7b"]
    assert result[0]["ownedBy"] == "ollama"


def test_discover_route_anthropic(monkeypatch) -> None:
    client = _mount_app()
    monkeypatch.setattr(
        models_route,
        "_discover_anthropic_models",
        lambda base_url, api_key: [{"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "ownedBy": "anthropic"}],
    )
    resp = client.post("/discover", json={"providerType": "anthropic", "baseUrl": "https://api.anthropic.com", "apiKey": "sk"})
    assert resp.status_code == 200
    assert resp.json()["models"][0]["id"] == "claude-3-5-sonnet-20241022"


def test_discover_route_gemini(monkeypatch) -> None:
    client = _mount_app()
    monkeypatch.setattr(
        models_route,
        "_discover_gemini_models",
        lambda base_url, api_key: [{"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "ownedBy": "google"}],
    )
    resp = client.post("/discover", json={"providerType": "gemini", "baseUrl": "https://generativelanguage.googleapis.com", "apiKey": "key"})
    assert resp.status_code == 200
    assert resp.json()["models"][0]["id"] == "gemini-1.5-pro"


def test_discover_route_ollama(monkeypatch) -> None:
    client = _mount_app()
    monkeypatch.setattr(
        models_route,
        "_discover_ollama_models",
        lambda base_url, api_key: [{"id": "llama3.1", "name": "llama3.1", "ownedBy": "ollama"}],
    )
    resp = client.post("/discover", json={"providerType": "ollama", "baseUrl": "http://localhost:11434", "apiKey": ""})
    assert resp.status_code == 200
    assert resp.json()["models"][0]["id"] == "llama3.1"


def test_discover_reuses_stored_key_for_existing_instance(monkeypatch) -> None:
    """编辑已保存配置、前端未重填 Key 时，后端取实例已加密 Key 解密复用（免去每次重输）。"""
    captured: dict[str, str] = {}

    async def _fake_find(*_a, **_k):
        return {"_id": "i1", "api_key_encrypted": "enc"}

    monkeypatch.setattr(models_route, "find_instance_by_id", _fake_find)
    monkeypatch.setattr(models_route, "_decrypt_api_key", lambda instance: ("sk-stored", ""))

    def _fake_discover(base_url, api_key):
        captured["api_key"] = api_key
        return [{"id": "gpt-4o", "name": "gpt-4o", "ownedBy": "openai"}]

    monkeypatch.setattr(models_route, "_discover_openai_compatible_models", _fake_discover)
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={
            "providerType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1",
            "apiKey": "",
            "instanceId": "507f1f77bcf86cd799439011",
        },
    )
    assert resp.status_code == 200
    assert captured["api_key"] == "sk-stored"
    assert resp.json()["models"][0]["id"] == "gpt-4o"


def test_discover_stored_key_instance_not_found_returns_400(monkeypatch) -> None:
    async def _fake_find(*_a, **_k):
        return None

    monkeypatch.setattr(models_route, "find_instance_by_id", _fake_find)

    def _should_not_run(*_a, **_k):
        raise AssertionError("_decrypt_api_key should not run when instance missing")

    monkeypatch.setattr(models_route, "_decrypt_api_key", _should_not_run)
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={
            "providerType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1",
            "apiKey": "",
            "instanceId": "507f1f77bcf86cd799439011",
        },
    )
    assert resp.status_code == 400
    assert "未找到" in resp.json()["detail"]


def test_discover_prefers_provided_key_over_stored(monkeypatch) -> None:
    """前端显式填了新 Key 时，直接用新 Key，不回退已存密钥。"""
    captured: dict[str, str] = {}

    async def _should_not_run(*_a, **_k):
        raise AssertionError("find_instance_by_id should not run when apiKey provided")

    monkeypatch.setattr(models_route, "find_instance_by_id", _should_not_run)

    def _fake_discover(base_url, api_key):
        captured["api_key"] = api_key
        return [{"id": "x", "name": "x", "ownedBy": ""}]

    monkeypatch.setattr(models_route, "_discover_openai_compatible_models", _fake_discover)
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={
            "providerType": "openai_compatible",
            "baseUrl": "https://api.openai.com/v1",
            "apiKey": "sk-new",
            "instanceId": "507f1f77bcf86cd799439011",
        },
    )
    assert resp.status_code == 200
    assert captured["api_key"] == "sk-new"


def test_discover_ollama_skips_stored_key_lookup(monkeypatch) -> None:
    """Ollama 无需 Key：即使带 instanceId 也不查库，直接用空 Key。"""
    captured: dict[str, str] = {}

    async def _should_not_run(*_a, **_k):
        raise AssertionError("find_instance_by_id should not run for ollama")

    monkeypatch.setattr(models_route, "find_instance_by_id", _should_not_run)

    def _fake_discover(base_url, api_key):
        captured["api_key"] = api_key
        return [{"id": "llama3.1", "name": "llama3.1", "ownedBy": "ollama"}]

    monkeypatch.setattr(models_route, "_discover_ollama_models", _fake_discover)
    client = _mount_app()
    resp = client.post(
        "/discover",
        json={
            "providerType": "ollama",
            "baseUrl": "http://localhost:11434",
            "apiKey": "",
            "instanceId": "507f1f77bcf86cd799439011",
        },
    )
    assert resp.status_code == 200
    assert captured["api_key"] == ""
