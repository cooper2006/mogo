from __future__ import annotations

import logging
import socket
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.db import get_db
from app.services.docling_runtime import docling_runtime_status
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    """存活 + 数据后端快照。"""
    payload: dict[str, Any] = {"status": "ok", "service": "mogo-document-processing-service"}
    try:
        from app.core import pg

        payload.update(pg.health_payload())
    except Exception:  # pragma: no cover - 健康检查自身绝不应抛错
        logger.warning("采集数据后端健康信息失败", exc_info=True)
    return payload


@router.get("/ready")
def ready(response: Response) -> dict:
    checks: dict[str, bool] = {}
    # 按当前后端命名检查项：mongo 模式下键名保持不变，避免影响既有探针。
    backend_key = "panweidb" if settings.effective_data_backend == "panweidb" else "mongo"
    try:
        get_db().command("ping")
        checks[backend_key] = True
    except Exception:
        checks[backend_key] = False

    parsed = urllib.parse.urlparse(settings.redis_url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 6379), timeout=2):
            checks["redis"] = True
    except Exception:
        checks["redis"] = False

    try:
        with urllib.request.urlopen(f"{settings.weaviate_endpoint.rstrip('/')}/v1/.well-known/ready", timeout=2):
            checks["weaviate"] = True
    except Exception:
        checks["weaviate"] = False

    try:
        checks["worker"] = bool(celery_app.control.inspect(timeout=1).ping())
    except Exception:
        checks["worker"] = False

    checks["docling"], _ = docling_runtime_status()

    is_ready = all(checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if is_ready else "degraded", "service": "mogo-document-processing-service", "checks": checks}
