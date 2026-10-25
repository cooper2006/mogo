"""023 T023 — document-parser 健康检查端点。

`/ready`（就绪，依赖可达性）：依赖不可达时返回 503。
- MongoDB：`db` 的 client ping
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response, status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


async def _check_mongodb() -> dict[str, Any]:
    from app.core.db import get_db

    payload: dict[str, Any] = {"backend": "mongo"}
    try:
        client = get_db()
        await client.admin.command("ping")
        payload["reachable"] = True
    except Exception:
        payload["reachable"] = False
    return payload


@router.get("/ready", tags=["system"])
async def ready(response: Response) -> dict[str, Any]:
    """就绪检查：所有关键依赖可达才返回 200，否则 503。"""
    checks = await _check_mongodb()
    all_ok = checks.get("reachable", False)
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
