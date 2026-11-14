"""Authenticated internal endpoint consumed only by the DSH model plugin."""

from __future__ import annotations

import json

from fastapi import APIRouter, Header
from starlette.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.dsh_runtime.model_gateway.service import (
    ModelGatewayFailure,
    ModelGatewayRequest,
    ModelGatewayService,
)
from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService


router = APIRouter(prefix="/internal/dsh/model", tags=["dsh-internal"])


def _model_gateway() -> ModelGatewayService:
    """从 application 取注入了 ProjectIdResolver 的 ModelGatewayService（FR-006）。"""
    from app.dsh_runtime.application import dsh_runtime_application

    if dsh_runtime_application.model_gateway is None:
        raise RuntimeError("DSH Runtime Application is not started")
    return dsh_runtime_application.model_gateway


def _token_service() -> ModelGatewayTokenService:
    settings = get_settings()
    secret = str(
        settings.DSH_MODEL_GATEWAY_SIGNING_SECRET
        or settings.ASKAI_ADMIN_JWT_SECRET
        or ""
    )
    return ModelGatewayTokenService(secret)


@router.post("/generate")
async def generate(
    request: ModelGatewayRequest,
    authorization: str = Header(default=""),
):
    if not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "model_gateway_unauthorized", "message": "missing bearer token", "retryable": False}},
        )
    try:
        claims = _token_service().verify(authorization.removeprefix("Bearer ").strip())
        events = await _model_gateway().stream(request, claims)

        async def ndjson_stream():
            async for event in events:
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

        return StreamingResponse(
            ndjson_stream(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "model_gateway_unauthorized", "message": str(exc), "retryable": False}},
        )
    except ModelGatewayFailure as exc:
        return JSONResponse(
            status_code=502 if exc.retryable else 400,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                }
            },
        )
