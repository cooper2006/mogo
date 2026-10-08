from __future__ import annotations

import secrets
import asyncio
import os
import socket
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.time_utils import utc_iso
from app.core.config import settings
from app.core.db import get_db
from app.core.tenant_identity import PLATFORM_TENANT_ID
from app.repositories.model_repository import ensure_indexes as ensure_model_indexes
from app.repositories.setup_repository import (
    acquire_setup_lock,
    ensure_indexes,
    get_setup_state,
    mark_platform_admin_created,
    release_setup_lock,
)
from app.services.platform_bootstrap import ensure_platform_admin, platform_admin_exists
from app.services.setup_model import (
    SetupModelError,
    get_active_setup_providers,
    test_setup_model,
)
from app.services.external_search_provider import ExternalSearchConfigError
from app.services.setup_external_search import (
    setup_provider_catalog,
    test_setup_search,
)

router = APIRouter()


class SetupServiceStatus(BaseModel):
    key: str
    label: str
    ok: bool
    message: str = ""
    core: bool = False


class SetupUrls(BaseModel):
    userWeb: str = ""
    adminWeb: str = ""
    desktopService: str = ""
    agentWebSocket: str = ""


class SetupStatusResponse(BaseModel):
    completed: bool
    orgName: str = ""
    tenantId: str = ""
    initializedAt: str = ""
    ready: bool = False
    platformAdminMissing: bool = False
    services: list[SetupServiceStatus] = Field(default_factory=list)
    urls: SetupUrls = Field(default_factory=SetupUrls)


class SetupModelRequest(BaseModel):
    providerId: str = Field(min_length=1)
    displayName: str = Field(min_length=1, max_length=80)
    modelName: str = Field(min_length=1, max_length=120)
    baseUrl: str = Field(min_length=1, max_length=300)
    apiVersion: str = Field(default="", max_length=40)
    apiKey: str = Field(min_length=1, max_length=600)
    capability: str = Field(default="chat", pattern=r"^(chat|embedding|rerank|vision|image)$")


class SetupExternalSearchRequest(BaseModel):
    provider: str = Field(pattern=r"^(tavily|serper|serpapi|baidu_qianfan|volc_ark|claw_search)$")
    apiKey: str = Field(min_length=1, max_length=1000)
    endpoint: str = Field(default="", max_length=500)
    baseUrl: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    query: str = Field(default="MOVO enterprise AI", max_length=300)


class SetupPlatformAdminRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=128)
    displayName: str = Field(default="平台管理员", min_length=2, max_length=64)


def _fmt(value: datetime | None) -> str:
    return utc_iso(value)


def _request_public_base(request: Request) -> str:
    configured = str(settings.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    scheme = str(request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",", 1)[0].strip()
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",", 1)[0].strip()
    return f"{scheme}://{host}".rstrip("/")


def _connection_urls(request: Request) -> SetupUrls:
    base = _request_public_base(request)
    ws_base = f"wss://{base[8:]}" if base.startswith("https://") else f"ws://{base[7:]}" if base.startswith("http://") else base
    return SetupUrls(
        userWeb=f"{base}/",
        adminWeb=f"{base}/admin/",
        desktopService=base,
        agentWebSocket=f"{ws_base}/api/agent/connect",
    )


async def _probe_http(key: str, label: str, url: str) -> SetupServiceStatus:
    def request_url() -> None:
        with urllib.request.urlopen(url, timeout=2.5) as response:
            if int(response.status) >= 400:
                raise RuntimeError(f"HTTP {response.status}")

    try:
        await asyncio.to_thread(request_url)
        return SetupServiceStatus(key=key, label=label, ok=True, message="已就绪")
    except Exception as exc:
        return SetupServiceStatus(key=key, label=label, ok=False, message=str(exc)[:160])


async def _probe_mongo() -> SetupServiceStatus:
    try:
        await get_db().command("ping")
        return SetupServiceStatus(key="mongo", label="MongoDB", ok=True, message="已就绪", core=True)
    except Exception as exc:
        return SetupServiceStatus(key="mongo", label="MongoDB", ok=False, message=str(exc)[:160], core=True)


async def _probe_redis() -> SetupServiceStatus:
    parsed = urllib.parse.urlparse(str(settings.redis_url or "redis://127.0.0.1:6379/0"))

    def connect() -> None:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 6379), timeout=2.5):
            return

    try:
        await asyncio.to_thread(connect)
        return SetupServiceStatus(key="redis", label="Redis", ok=True, message="已就绪")
    except Exception as exc:
        return SetupServiceStatus(key="redis", label="Redis", ok=False, message=str(exc)[:160])


async def _probe_storage() -> SetupServiceStatus:
    paths = [settings.knowledge_local_storage_dir, settings.admin_static_dir]
    try:
        for raw_path in paths:
            path = os.path.abspath(os.path.expanduser(str(raw_path)))
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                raise PermissionError(f"目录不可写: {path}")
        return SetupServiceStatus(key="storage", label="持久化存储", ok=True, message="已就绪")
    except Exception as exc:
        return SetupServiceStatus(key="storage", label="持久化存储", ok=False, message=str(exc)[:160])


async def _deployment_services() -> list[SetupServiceStatus]:
    chat_health = f"{str(settings.backend_base_url).rstrip('/')}/ready"
    document_ready = f"{str(settings.document_processing_base_url).rstrip('/')}/api/ready"
    weaviate_ready = f"{str(settings.weaviate_endpoint).rstrip('/')}/v1/.well-known/ready"
    results = await asyncio.gather(
        _probe_mongo(),
        _probe_redis(),
        _probe_storage(),
        _probe_http("chat-api", "Chat API 与 DSH Runtime", chat_health),
        _probe_http("document-processing", "文档处理与 Worker", document_ready),
        _probe_http("weaviate", "Weaviate", weaviate_ready),
    )
    return list(results)


async def _ensure_setup_open() -> None:
    state = await get_setup_state()
    if state and bool(state.get("completed")):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="setup already completed")


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(request: Request) -> SetupStatusResponse:
    await ensure_indexes()
    state = await get_setup_state()
    services = await _deployment_services()
    platform_admin_present = await platform_admin_exists()
    completed = platform_admin_present or bool(state and state.get("completed"))
    platform_admin_missing = (not completed) and not str(settings.platform_admin_password or "").strip()
    common = {
        # Only core services (MongoDB) gate readiness; the rest are advisory.
        "ready": all(item.ok for item in services if item.core),
        "platformAdminMissing": bool(platform_admin_missing),
        "services": services,
        "urls": _connection_urls(request),
    }
    if not completed:
        return SetupStatusResponse(completed=False, **common)
    return SetupStatusResponse(
        completed=True,
        orgName=str((state or {}).get("org_name") or ""),
        tenantId=str((state or {}).get("tenant_id") or PLATFORM_TENANT_ID),
        initializedAt=_fmt((state or {}).get("updated_at")),
        **common,
    )


@router.get("/model-providers")
async def setup_model_providers() -> list[dict[str, object]]:
    await _ensure_setup_open()
    await ensure_model_indexes()
    return await get_active_setup_providers()


@router.post("/model/test")
async def setup_model_test(payload: SetupModelRequest) -> dict[str, object]:
    await _ensure_setup_open()
    await ensure_model_indexes()
    try:
        message = await test_setup_model(payload.model_dump())
    except SetupModelError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"success": True, "message": message}


@router.get("/search-providers")
async def setup_search_providers() -> list[dict[str, str]]:
    await _ensure_setup_open()
    return setup_provider_catalog()


@router.post("/search/test")
async def setup_search_test(payload: SetupExternalSearchRequest) -> dict[str, Any]:
    await _ensure_setup_open()
    try:
        results = await test_setup_search(payload.model_dump())
    except ExternalSearchConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)[:1000]) from exc
    if not results:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="搜索服务未返回结果")
    return {"success": True, "message": "搜索连接测试成功", "resultCount": len(results)}


@router.post("/platform-admin")
async def setup_platform_admin(payload: SetupPlatformAdminRequest) -> dict[str, Any]:
    """Create the platform super-admin (one-time bootstrap).

    The bootstrap wizard does **not** create a tenant (decision 11): tenants are
    created later from the platform console. Returns 409 when a platform admin
    already exists or when the bootstrap lock is held.
    """
    await ensure_indexes()
    if await platform_admin_exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="platform admin already exists")
    await _ensure_setup_open()

    lock_token = secrets.token_urlsafe(32)
    if not await acquire_setup_lock(lock_token):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="setup is already completed or initialization is in progress",
        )
    username = payload.username.strip()
    display_name = payload.displayName.strip()
    try:
        await ensure_platform_admin(username=username, password=payload.password, display_name=display_name)
        await mark_platform_admin_created(lock_token=lock_token, username=username, display_name=display_name)
    finally:
        await release_setup_lock(lock_token)
    return {"completed": True, "tenantId": PLATFORM_TENANT_ID, "username": username}
