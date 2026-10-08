from __future__ import annotations
from app.infrastructure.observability.config import log_print

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.tenant import resolve_tenant_id
from app.llm.configured_image_models import list_image_model_options
from app.llm.configured_models import (
    ModelConfigError,
    get_llm_client_by_model_id,
    list_model_options,
    list_chat_model_options,
    update_model_health,
)
from app.services.image_generation import generate_image_asset
from app.llm.types import Message, Role
from app.api.principal import require_api_principal

router = APIRouter(dependencies=[Depends(require_api_principal)])


class ModelTestPayload(BaseModel):
    prompt: str = Field(default="请用一句话回复当前模型连接测试。", max_length=500)
    tenant_id: str = Field(default="default")


class ImageModelTestPayload(BaseModel):
    prompt: str = Field(default="生成一张简洁的科技感封面背景，不要文字。", max_length=2000)
    tenant_id: str = Field(default="default")
    size: str | None = Field(default=None, max_length=40)


@router.get("/models/available")
async def available_models(
    tenant_id: str = Query(default="default"),
    capability: str = Query(default="chat"),
) -> dict[str, Any]:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    token = str(capability or "chat").strip() or "chat"
    if token == "chat":
        options = await list_chat_model_options(resolved_tenant_id)
    else:
        options = await list_model_options(resolved_tenant_id, capability=token)
    return {"code": 0, "data": options}


@router.get("/models/images/available")
async def available_image_models(tenant_id: str = Query(default="default")) -> dict[str, Any]:
    options = await list_image_model_options(resolve_tenant_id(tenant_id))
    return {"code": 0, "data": options}


@router.post("/models/{model_id}/test/stream")
async def stream_model_test(model_id: str, payload: Optional[ModelTestPayload] = None) -> StreamingResponse:
    tenant_id = resolve_tenant_id((payload.tenant_id if payload else "") or "default")
    prompt = (payload.prompt if payload else "") or "请用一句话回复当前模型连接测试。"

    async def event_stream():
        final_text = ""
        try:
            await update_model_health(model_id, tenant_id, "unknown", "")
            yield _sse({"type": "start", "message": "正在连接模型..."})
            client = await get_llm_client_by_model_id(
                model_id,
                tenant_id=tenant_id,
                streaming=True,
                intent="chat",
                stage="model_connectivity_test",
                output_spec={"tenant_id": tenant_id, "model_id": model_id},
            )
            messages = [
                Message(role=Role.SYSTEM, content="You are a concise model connectivity test assistant."),
                Message(role=Role.USER, content=prompt),
            ]
            async for chunk in client.astream(messages):
                text = str(chunk.content or "")
                if text:
                    final_text += text
                    yield _sse({"type": "delta", "content": text})
            await update_model_health(model_id, tenant_id, "healthy", "")
            yield _sse({"type": "done", "message": final_text or "模型连接测试成功。"})
        except ModelConfigError as exc:
            await update_model_health(model_id, tenant_id, "failed", str(exc))
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:
            log_print(f"[api.endpoints.models] model stream test failed: {exc}", flush=True)
            message = f"模型连接测试失败: {exc}"
            await update_model_health(model_id, tenant_id, "failed", message)
            yield _sse({"type": "error", "message": message})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/models/{model_id}/test")
async def model_test(model_id: str, payload: Optional[ModelTestPayload] = None) -> dict[str, Any]:
    tenant_id = resolve_tenant_id((payload.tenant_id if payload else "") or "default")
    prompt = (payload.prompt if payload else "") or "请用一句话回复当前模型连接测试。"
    try:
        client = await get_llm_client_by_model_id(
            model_id,
            tenant_id=tenant_id,
            streaming=False,
            intent="chat",
            stage="model_connectivity_test",
            output_spec={"tenant_id": tenant_id, "model_id": model_id},
        )
        response = await client.ainvoke(
            [
                Message(role=Role.SYSTEM, content="You are a concise model connectivity test assistant."),
                Message(role=Role.USER, content=prompt),
            ],
        )
        await update_model_health(model_id, tenant_id, "healthy", "")
        return {"code": 0, "data": {"success": True, "status": "healthy", "message": str(response.content or "")}}
    except ModelConfigError as exc:
        await update_model_health(model_id, tenant_id, "failed", str(exc))
        return {"code": 0, "data": {"success": False, "status": "failed", "message": str(exc)}}
    except Exception as exc:
        log_print(f"[api.endpoints.models] model test failed: {exc}", flush=True)
        message = f"模型连接测试失败: {exc}"
        await update_model_health(model_id, tenant_id, "failed", message)
        return {"code": 0, "data": {"success": False, "status": "failed", "message": message}}


@router.post("/models/{model_id}/test-image")
async def image_model_test(model_id: str, payload: Optional[ImageModelTestPayload] = None) -> dict[str, Any]:
    tenant_id = resolve_tenant_id((payload.tenant_id if payload else "") or "default")
    prompt = (payload.prompt if payload else "") or "生成一张简洁的科技感封面背景，不要文字。"
    size = (payload.size if payload else None) or None
    try:
        result = await generate_image_asset(
            prompt=prompt,
            user_id="admin_model_test",
            size=size,
            output_spec={"tenant_id": tenant_id, "image_model_id": model_id},
            file_prefix="model_test_image",
        )
        await update_model_health(model_id, tenant_id, "healthy", "")
        return {
            "code": 0,
            "data": {
                "success": True,
                "status": "healthy",
                "image_url": str(result.get("image_url") or ""),
                "object_path": str(result.get("object_path") or ""),
                "request_id": str(result.get("request_id") or ""),
                "model_source": str(result.get("model_source") or ""),
                "provider_type": str(result.get("provider_type") or ""),
                "runtime_kind": str(result.get("runtime_kind") or ""),
            },
        }
    except Exception as exc:
        log_print(f"[api.endpoints.models] image model test failed: {exc}", flush=True)
        message = f"图片模型连接测试失败: {exc}"
        await update_model_health(model_id, tenant_id, "failed", message)
        return {"code": 0, "data": {"success": False, "status": "failed", "message": message}}


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
