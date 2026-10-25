"""023 T016 — admin-api 健康检查端点。

`/health`（存活）+ `/ready`（就绪，依赖可达性）+ 启动自检结果缓存。

`/ready` 语义（FR-5）：依赖不可达时返回 503，不抛异常。
- PanWeiDB 模式：`pg.ping_async()`
- MongoDB 模式：`db` 的 client ping（`admin_db` 集合 count 1）
- Redis：`rate_limiter.get_default_limiter().backend` == "redis" 时 ping
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response, status

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


async def _check_panweidb() -> dict[str, Any]:
    from app.core import pg

    payload: dict[str, Any] = {"backend": "panweidb"}
    try:
        payload["reachable"] = await pg.ping_async()
    except Exception:
        payload["reachable"] = False
    return payload


async def _check_mongodb() -> dict[str, Any]:
    """023 T083：ping 走熔断器 + 5s 操作预算（FR-21/FR-22）。"""
    from app.core import db, resilience

    payload: dict[str, Any] = {"backend": "mongo"}
    try:
        client = db.get_admin_db()
    except Exception as exc:
        payload["reachable"] = False
        payload["reason"] = resilience.PROBE_ERROR
        payload["error"] = type(exc).__name__
        return payload

    result = await resilience.probe_mongo(client)
    payload["reachable"] = result["ok"]
    payload["reason"] = result["reason"]
    if result.get("error"):
        payload["error"] = result["error"]
    return payload


async def _check_redis() -> dict[str, Any]:
    payload: dict[str, Any] = {"redis": "skipped"}
    try:
        from app.core import resilience
        from app.core.rate_limiter import get_default_limiter

        limiter = get_default_limiter()
        client = getattr(limiter, "_redis", None)
        if limiter.backend != "redis" or client is None:
            payload["redis"] = "not_configured"
            return payload
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
    backend = settings.effective_data_backend

    if backend == "panweidb":
        checks = await _check_panweidb()
    else:
        checks = await _check_mongodb()

    redis_check = await _check_redis()
    checks.update(redis_check)

    all_ok = checks.get("reachable", False) and checks.get("redis") in {"ok", "not_configured"}
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
