from __future__ import annotations

from typing import Any

import httpx
from fastapi import UploadFile

from app.core.config import get_settings


class KnowledgeLifecycleClient:
    async def upload(
        self, *, main_id: str, owner_user_id: str, resource_id: str,
        file: UploadFile, name: str, description: str, tags: list[str],
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        headers = {"X-MOVO-Service-Token": str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")}
        data = {
            "mainId": main_id,
            "ownerUserId": owner_user_id,
            "resourceId": resource_id,
            "name": name,
            "description": description,
            "tags": ",".join(tags),
            "replaceExisting": "true" if replace_existing else "false",
        }
        files = {"file": (file.filename or "document", file.file, file.content_type or "application/octet-stream")}
        base_url = str(settings.ADMIN_API_BASE_URL or "http://127.0.0.1:8100").rstrip("/")
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{base_url}/api/internal/personal-knowledge/documents",
                data=data, files=files, headers=headers,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"knowledge_lifecycle_upload_failed:{response.status_code}:{response.text[:500]}")
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else {}

    async def action(self, *, action: str, main_id: str, owner_user_id: str, resource_id: str) -> dict[str, Any]:
        settings = get_settings()
        base_url = str(settings.ADMIN_API_BASE_URL or "http://127.0.0.1:8100").rstrip("/")
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/api/internal/personal-knowledge/{resource_id}/{action}",
                json={"mainId": main_id, "ownerUserId": owner_user_id},
                headers={"X-MOVO-Service-Token": str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"knowledge_lifecycle_{action}_failed:{response.status_code}:{response.text[:500]}")
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else {}


knowledge_lifecycle_client = KnowledgeLifecycleClient()
