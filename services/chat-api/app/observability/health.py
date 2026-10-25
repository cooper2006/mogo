"""023 T020 — chat-api 健康检查端点。

`/ready`（就绪，依赖可达性）：依赖不可达时返回 503。
- MongoDB：`db` 的 client ping
- Redis：ping
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response, status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


async def _check_mongodb() -> dict[str, Any]:
    """023 T083：ping 走熔断器 + 5s 操作预算（FR-21/FR-22）。

    `reason` 区分「熔断打开」「超时」「其它错误」，便于排障时判断是依赖挂了
    还是我们主动快速失败。
    """
    from app.core import resilience
    from app.core.db import get_db

    payload: dict[str, Any] = {"backend": "mongo"}
    try:
        database = get_db()
    except Exception as exc:
        payload["reachable"] = False
        payload["reason"] = resilience.PROBE_ERROR
        payload["error"] = type(exc).__name__
        return payload
    if database is None:
        payload["reachable"] = False
        payload["reason"] = "not_initialized"
        return payload

    result = await resilience.probe_mongo(database)
    payload["reachable"] = result["ok"]
    payload["reason"] = result["reason"]
    if result.get("error"):
        payload["error"] = result["error"]
    return payload


async def _check_redis() -> dict[str, Any]:
    payload: dict[str, Any] = {"redis": "skipped"}
    try:
        from app.dsh_runtime.runtime_lock import get_runtime_lock

        lock = get_runtime_lock()
        client = getattr(lock, "_redis", None)
        if client is None:
            payload["redis"] = "not_configured"
            return payload
        from app.core import resilience

        resilience.register_redis_pool(client)
        result = resilience.probe_redis(client)
        payload["redis"] = "ok" if result["ok"] else "unreachable"
        payload["redis_reason"] = result["reason"]
    except Exception:
        payload["redis"] = "unreachable"
    return payload


@router.get("/ready", tags=["system"])
async def ready(response: Response) -> dict[str, Any]:
    """就绪检查：所有关键依赖可达才返回 200，否则 503。"""
    checks = await _check_mongodb()
    redis_check = await _check_redis()
    checks.update(redis_check)

    all_ok = checks.get("reachable", False) and checks.get("redis") in {"ok", "not_configured"}
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
