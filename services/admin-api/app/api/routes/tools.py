from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.api.time_utils import utc_iso
from app.api.tool_limits import validate_mcp_activation
from app.core.config import settings
from app.core.db import get_db
from app.governance import GateContext, gatekeeper
from app.services.organization_tools import (
    organization_tool_fields,
    organization_tool_query,
)

router = APIRouter()

TOOL_TYPES = {"http", "mcp"}
TOOL_STATUSES = {"active", "disabled"}
MONGO_DOLLAR_PREFIX = "\uff04"
MONGO_DOT = "\uff0e"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _mongo_restore_key(key: Any) -> str:
    text = str(key)
    if text.startswith(MONGO_DOLLAR_PREFIX):
        text = f"${text[1:]}"
    return text.replace(MONGO_DOT, ".")


def _mongo_restore_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {_mongo_restore_key(key): _mongo_restore_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mongo_restore_value(item) for item in value]
    return value


def _time_text(value: Any) -> str:
    return utc_iso(value)


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc.get("_id") or ""),
        "mainId": str(doc.get("tenant_id") or "default"),
        "name": str(doc.get("name") or ""),
        "type": str(doc.get("type") or "http"),
        "description": str(doc.get("description") or ""),
        "usageHint": str(doc.get("usage_hint") or ""),
        "tags": [str(item) for item in _safe_list(doc.get("tags")) if str(item).strip()],
        "status": str(doc.get("status") or "disabled"),
        "config": _safe_dict(doc.get("config")),
        "lastTestStatus": str(doc.get("last_test_status") or "untested"),
        "lastTestAt": _time_text(doc.get("last_test_at")),
        "lastTestMessage": str(doc.get("last_test_message") or ""),
        "discoveredTools": _safe_list(_mongo_restore_value(doc.get("discovered_tools"))),
        "createdAt": _time_text(doc.get("created_at")),
        "updatedAt": _time_text(doc.get("updated_at")),
    }


def _normalize_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if not partial or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="工具名称不能为空")
        patch["name"] = name[:120]
    if not partial or "type" in payload:
        tool_type = str(payload.get("type") or "http").strip().lower()
        if tool_type not in TOOL_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="工具类型只支持 HTTP 接口或 MCP 服务")
        patch["type"] = tool_type
    if not partial or "description" in payload:
        patch["description"] = str(payload.get("description") or "").strip()
    if not partial or "usageHint" in payload or "usage_hint" in payload:
        patch["usage_hint"] = str(payload.get("usageHint", payload.get("usage_hint", "")) or "").strip()
    if not partial or "tags" in payload:
        tags: list[str] = []
        for item in _safe_list(payload.get("tags")):
            tag = str(item or "").strip()
            if tag and tag not in tags:
                tags.append(tag[:40])
        patch["tags"] = tags[:20]
    if not partial or "status" in payload:
        tool_status = str(payload.get("status") or "disabled").strip().lower()
        if tool_status not in TOOL_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态只支持 active 或 disabled")
        patch["status"] = tool_status
    if not partial or "config" in payload:
        patch["config"] = _safe_dict(payload.get("config"))
    return patch


def _validate_final_activation(existing: dict[str, Any] | None, patch: dict[str, Any]) -> None:
    existing = existing or {}
    tool_type = str(patch.get("type", existing.get("type", "http")) or "")
    tool_status = str(patch.get("status", existing.get("status", "disabled")) or "")
    config = _safe_dict(patch.get("config", existing.get("config", {})))
    error = validate_mcp_activation(tool_type=tool_type, status=tool_status, config=config)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)


def _backend_url(path: str, tenant_id: str) -> str:
    base_url = str(settings.backend_base_url or "http://127.0.0.1:8000").rstrip("/")
    separator = "&" if "?" in path else "?"
    return f"{base_url}/api/external-tools{path}{separator}{urllib.parse.urlencode({'mainId': main_id})}"


def _config_timeout_seconds(config: dict[str, Any], default: int = 35) -> int:
    timeout_seconds = config.get("timeoutSeconds", config.get("timeout_seconds", default))
    try:
        value = float(timeout_seconds)
    except (TypeError, ValueError):
        value = float(default)
    if value <= 0:
        value = float(default)
    return int(max(default, min(value + 10, 180)))


def _tool_timeout_seconds(payload: Any, default: int = 35) -> int:
    body = _safe_dict(payload)
    tool = _safe_dict(body.get("tool"))
    return _config_timeout_seconds(_safe_dict(tool.get("config")), default=default)


def _request_backend(method: str, path: str, tenant_id: str, body: Any | None = None, timeout: int = 35) -> Any:
    data = None
    headers = {
        "Accept": "application/json",
        "X-MOVO-Service-Token": settings.backend_service_token,
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(_backend_url(path, tenant_id), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("detail") or parsed.get("message") or detail
        except json.JSONDecodeError:
            message = detail or str(exc)
        raise HTTPException(status_code=exc.code, detail=message) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"backend 不可用：{exc.reason}") from exc
    return json.loads(raw) if raw else {"code": 0, "data": None}


def _backend_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response:
        return response.get("data")
    return response


class ToolPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern=r"^(http|mcp)$")
    description: str = ""
    usageHint: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = Field(default="disabled", pattern=r"^(active|disabled)$")
    config: dict[str, Any] = Field(default_factory=dict)


class ToolPatchPayload(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    type: Optional[str] = Field(default=None, pattern=r"^(http|mcp)$")
    description: Optional[str] = None
    usageHint: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern=r"^(active|disabled)$")
    config: Optional[dict[str, Any]] = None


class ToolDescriptionGeneratePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="http", pattern=r"^(http|mcp)$")
    existingDescription: str = ""


@router.get("")
async def list_tools(current_user: dict = Depends(get_current_admin_user)) -> list[dict[str, Any]]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    cursor = db.external_tools.find(organization_tool_query(tenant_id)).sort("updated_at", -1)
    return [_serialize(doc) async for doc in cursor]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tool(payload: ToolPayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    now = _now()
    doc = {
        "_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        **organization_tool_fields(),
        **_normalize_payload(payload.model_dump()),
        "status": "disabled",
        "last_test_status": "untested",
        "last_test_at": None,
        "last_test_message": "",
        "discovered_tools": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.external_tools.insert_one(doc)
    return _serialize(doc)


@router.get("/{tool_id}")
async def get_tool(tool_id: str, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    doc = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    return _serialize(doc)


@router.put("/{tool_id}")
async def update_tool(tool_id: str, payload: ToolPayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    existing = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    patch = {**_normalize_payload(payload.model_dump()), "updated_at": _now()}
    _validate_final_activation(existing, patch)
    result = await db.external_tools.update_one(organization_tool_query(tenant_id, _id=str(tool_id)), {"$set": patch})
    if not result.matched_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    doc = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    return _serialize(doc or {})


@router.patch("/{tool_id}")
async def patch_tool(tool_id: str, payload: ToolPatchPayload, current_user: dict = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    existing = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    patch = _normalize_payload(payload.model_dump(exclude_unset=True), partial=True)
    if patch:
        _validate_final_activation(existing, patch)
        patch["updated_at"] = _now()
        result = await db.external_tools.update_one(organization_tool_query(tenant_id, _id=str(tool_id)), {"$set": patch})
        if not result.matched_count:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    doc = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    return _serialize(doc)


@router.delete("/{tool_id}")
async def delete_tool(tool_id: str, current_user: dict = Depends(get_current_admin_user)) -> dict[str, str]:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    result = await db.external_tools.delete_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not result.deleted_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具连接不存在")
    return {"id": tool_id}


@router.post("/{tool_id}/test")
async def test_tool(tool_id: str, request: Request, response: Response, current_user: dict = Depends(get_current_admin_user)) -> Any:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    doc = await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业工具连接不存在")
    payload = await request.json()
    await _enforce_gate(str(tool_id), tenant_id, current_user, payload)
    timeout = _config_timeout_seconds(_safe_dict((doc or {}).get("config")))
    result = _backend_data(_request_backend("POST", f"/{tool_id}/test", tenant_id, payload, timeout=timeout))
    response.headers["X-MOVO-Operation-Result"] = "success" if _operation_succeeded(result) else "failed"
    return result


@router.post("/test-draft")
async def test_draft_tool(request: Request, response: Response, current_user: dict = Depends(get_current_admin_user)) -> Any:
    tenant_id = str(current_user.get("tenant_id") or "default")
    payload = await request.json()
    tool_id = str(payload.get("id") or payload.get("tool_id") or "test-draft")
    await _enforce_gate(tool_id, tenant_id, current_user, payload)
    result = _backend_data(_request_backend("POST", "/test-draft", tenant_id, payload, timeout=_tool_timeout_seconds(payload)))
    response.headers["X-MOVO-Operation-Result"] = "success" if _operation_succeeded(result) else "failed"
    return result


async def _enforce_gate(tool_id: str, tenant_id: str, current_user: dict, payload: Any) -> None:
    """Run the six-layer gatekeeper before executing a tool (feature 001, T006).

    Denials map to HTTP status by layer: identity/RBAC -> 403, approval pending ->
    409 (+ token), quota -> 429. A tool is identified by its id; the actor is the
    admin user with its bound position roles.
    """
    # Admin accounts carry no position-role bindings (006 binds roles to *employees*
    # in end_user_position_roles). Without a fallback the RBAC layer would see an
    # empty role set and fail closed on every admin tool call — the original
    # breakage (001 audit, 2026-10-03). Admin console calls run under the tenant's
    # full-access preset, which is exactly what a platform/org admin is.
    roles = current_user.get("role_ids") or current_user.get("roles") or []
    if not roles and tenant_id:
        roles = [f"system:{tenant_id}:full_access_admin"]
    # FR-2 resume: a caller re-enters a suspended call carrying its approval ticket.
    # Only a ticket a human approver already approved is consumable by the gate.
    _payload = _safe_dict(payload)
    annotations: dict[str, Any] = {}
    _approval_token = str(_payload.get("approvalToken") or _payload.get("approval_token") or "")
    if _approval_token:
        annotations["approval_token"] = _approval_token
        annotations["approval_action_id"] = str(
            _payload.get("approvalActionId") or _payload.get("approval_action_id") or ""
        )
    ctx = GateContext(
        tool=str(tool_id),
        tenant_id=tenant_id,
        user_id=str(current_user.get("user_id") or current_user.get("id") or ""),
        roles=[str(r) for r in roles],
        request=_payload,
        scope="tool",
        annotations=annotations,
    )
    # US2: resolve the tool's registered risk tier so the autonomy matrix can act.
    from app.governance import risk as governance_risk

    ctx.risk_level = await governance_risk.risk_level_for(tenant_id=tenant_id, tool=str(tool_id))
    ctx.autonomy_level = str(current_user.get("autonomy_level") or "L3")
    verdict = await gatekeeper.evaluate(str(tool_id), ctx)
    if verdict.allowed:
        return
    detail: dict[str, Any] = {"layer": verdict.layer, "reason": verdict.reason}
    approval_info = verdict.detail.get("approval") if isinstance(verdict.detail.get("approval"), dict) else None
    if verdict.layer == "approval" and approval_info:
        if approval_info.get("token"):
            detail["approval_token"] = approval_info["token"]
        if approval_info.get("action_id"):
            detail["approval_action_id"] = approval_info["action_id"]
    if verdict.detail.get("scope"):
        detail["quota"] = verdict.detail
    raise HTTPException(status_code=verdict.status_code, detail=detail)


def _operation_succeeded(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("success") is False or str(result.get("status") or "").lower() in {"failed", "error"}:
        return False
    return True


@router.post("/{tool_id}/discover")
async def discover_tool(tool_id: str, current_user: dict = Depends(get_current_admin_user)) -> Any:
    tenant_id = str(current_user.get("tenant_id") or "default")
    db = get_db()
    if not await db.external_tools.find_one(organization_tool_query(tenant_id, _id=str(tool_id)), {"_id": 1}):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="企业工具连接不存在")
    return _backend_data(_request_backend("POST", f"/{tool_id}/discover", tenant_id, {}))


@router.post("/generate-description")
async def generate_tool_description(payload: ToolDescriptionGeneratePayload, current_user: dict = Depends(get_current_admin_user)) -> Any:
    tenant_id = str(current_user.get("tenant_id") or "default")
    body = payload.model_dump()
    return _backend_data(_request_backend("POST", "/generate-description", tenant_id, body))


async def ensure_indexes() -> None:
    db = get_db()
    await db.external_tools.create_index([("tenant_id", 1), ("updated_at", -1)])
    await db.external_tools.create_index([("tenant_id", 1), ("status", 1), ("type", 1)])
    await db.external_tools.create_index([("tenant_id", 1), ("scope", 1), ("updated_at", -1)])
    from app.governance import schema as governance_schema

    await governance_schema.ensure_indexes()
