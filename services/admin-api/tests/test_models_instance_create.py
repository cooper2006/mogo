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
from app.repositories import model_repository


class _FakeCollection:
    def __init__(self) -> None:
        self.doc: dict | None = None

    async def insert_one(self, doc):
        self.doc = doc
        return SimpleNamespace(inserted_id="01a1d46f5292742358543be5fee51be4")


class _FakeDB:
    def __init__(self) -> None:
        self.collection = _FakeCollection()

    def __getitem__(self, _name):
        return self.collection


def _instance_payload(**overrides):
    payload = {
        "tenant_id": "tenant",
        "provider_id": "01a0e2d92dd8366db4feaa06e9afd35b",
        "group_id": "",
        "display_name": "组内成员",
        "model_name": "gpt-example",
        "api_key": "",
        "api_secret": "",
        "base_url": "",
        "api_version": "",
        "capabilities": ["chat"],
        "max_context_tokens": 0,
        "status": "active",
        "is_default": False,
        "priority": 100,
    }
    payload.update(overrides)
    return payload


def test_create_instance_persists_group_id(monkeypatch) -> None:
    fake = _FakeDB()
    monkeypatch.setattr(model_repository, "get_db", lambda: fake)
    group_id = "01a1d46f5294db764394442fef548426"

    asyncio.run(model_repository.create_instance(_instance_payload(group_id=group_id)))

    assert fake.collection.doc is not None
    assert fake.collection.doc["group_id"] == group_id
    assert fake.collection.doc["base_url"] == ""
    assert fake.collection.doc["api_key_encrypted"] == ""


def test_create_instance_without_group_stores_empty_group_id(monkeypatch) -> None:
    fake = _FakeDB()
    monkeypatch.setattr(model_repository, "get_db", lambda: fake)

    asyncio.run(model_repository.create_instance(_instance_payload()))

    assert fake.collection.doc is not None
    assert fake.collection.doc["group_id"] == ""


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
