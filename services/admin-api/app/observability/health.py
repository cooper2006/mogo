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
    from app.core import db

    payload: dict[str, Any] = {"backend": "mongo"}
    try:
        client = db.get_admin_db()
        # motor 的 ping 需要 admin 库
        await client.admin.command("ping")
        payload["reachable"] = True
    except Exception:
        payload["reachable"] = False
    return payload


async def _check_redis() -> dict[str, Any]:
    payload: dict[str, Any] = {"redis": "skipped"}
    try:
        from app.core.rate_limiter import get_default_limiter

        limiter = get_default_limiter()
        if limiter.backend == "redis" and limiter._redis is not None:
            limiter._redis.ping()
            payload["redis"] = "ok"
        else:
            payload["redis"] = "not_configured"
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
