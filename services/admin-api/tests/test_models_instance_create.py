"""模型实例创建接口的凭据校验口径。

Ollama 本地部署没有凭据：前端「获取模型列表」按 providerType 豁免了 Ollama，
后端创建接口必须用同一口径，否则 ollama 实例永远以 400「API Key 不能为空」被拒。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api.routes import models


def _patch_common(monkeypatch, provider_lookup, provider: dict) -> None:
    monkeypatch.setattr(models, "find_provider_by_id", provider_lookup)
    monkeypatch.setattr(models, "list_providers", lambda: asyncio.sleep(0, result=[provider]))


def test_ollama_instance_can_be_created_without_api_key(monkeypatch) -> None:
    provider_id = ObjectId()
    model_id = ObjectId()
    provider = {"_id": provider_id, "name": "Ollama（本地）", "provider_type": "ollama", "status": "active"}
    saved: dict = {}

    async def provider_lookup(_id):
        return provider

    async def create(payload):
        saved.update(payload)
        return model_id

    async def find(_id, _tenant):
        return {"_id": model_id, "provider_id": provider_id, **saved}

    _patch_common(monkeypatch, provider_lookup, provider)
    monkeypatch.setattr(models, "create_instance", create)
    monkeypatch.setattr(models, "find_instance_by_id", find)
    monkeypatch.setattr(models, "get_admin_product_extension", lambda: SimpleNamespace(model_created=[]))

    result = asyncio.run(models.post_model_instance(
        models.ModelInstancePayload(providerId=str(provider_id), displayName="本地模型",
                                    modelName="llama3", baseUrl="http://ollama:11434"),
        {"tenant_id": "tenant"},
    ))

    assert saved["api_key"] == ""
    assert result["modelName"] == "llama3"


def test_non_ollama_instance_still_requires_api_key(monkeypatch) -> None:
    provider_id = ObjectId()
    provider = {"_id": provider_id, "name": "OpenAI", "provider_type": "openai_compatible", "status": "active"}

    async def provider_lookup(_id):
        return provider

    _patch_common(monkeypatch, provider_lookup, provider)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(models.post_model_instance(
            models.ModelInstancePayload(providerId=str(provider_id), displayName="文本",
                                        modelName="gpt-example"),
            {"tenant_id": "tenant"},
        ))

    assert exc.value.status_code == 400
    assert exc.value.detail == "API Key 不能为空"
