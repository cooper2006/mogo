from __future__ import annotations
from app.infrastructure.observability.config import log_print

import hmac
from dataclasses import dataclass
from typing import Literal

from typing import Any

from fastapi import Header, HTTPException, Request

from app.core.config import get_settings
from app.core.tenant import resolve_tenant_id
from app.services.end_user_session import resolve_session_user


@dataclass(frozen=True)
class ApiPrincipal:
    kind: Literal["end_user", "admin_service"]
    tenant_id: str
    user_id: str = ""


def _matches(value: str, expected: str) -> bool:
    return bool(value and expected and hmac.compare_digest(value, expected))


async def _assert_end_user_scope(request: Request, principal: ApiPrincipal) -> None:
    claims: dict[str, str] = {}
    for key in ("userId", "user_id", "tenantId", "tenant_id"):
        value = request.query_params.get(key)
        if value:
            claims[key] = value

    content_type = str(request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                for key in ("userId", "user_id", "tenantId", "tenant_id"):
                    value = body.get(key)
                    if value:
                        claims[key] = str(value)
        elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            for key in ("userId", "user_id", "tenantId", "tenant_id"):
                value = form.get(key)
                if isinstance(value, str) and value:
                    claims[key] = value
    except Exception as exc:
        log_print(f"[principal] JSON body parse failed: {exc}", flush=True)

    claimed_user = claims.get("userId") or claims.get("user_id")
    if claimed_user and claimed_user != principal.user_id:
        raise HTTPException(status_code=403, detail="user_scope_mismatch")

    claimed_main = claims.get("tenantId") or claims.get("tenant_id")
    if claimed_main and resolve_tenant_id(claimed_main) != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_scope_mismatch")


#: 022 FR-12（T020）：本服务接受的调用方服务身份。
EXPECTED_CALLER_SERVICE_ID = "admin-api"
_LEGACY_TOKEN_ENV_NAMES = ("ADMIN_BACKEND_SERVICE_TOKEN",)

# 022 T028：服务身份权限最小化。
# admin-api 调本服务（chat-api）时，令牌必须携带对应端点要求的权限码。
# 命名约定与 admin-api 侧的 GATEKEEPER_ENDPOINT_SCOPES 对称：``<领域>.<动作>``。
SCOPE_MODELS_LIST = "models.list"
SCOPE_SKILLS_LIST = "skills.list"
SCOPE_EXTERNAL_TOOLS_LIST = "external_tools.list"

#: 请求路径前缀 -> 所需 scope（按最长前缀匹配）。
SERVICE_SCOPE_REGISTRY: dict[str, str] = {
    "/api/v1/models": SCOPE_MODELS_LIST,
    "/api/v1/skills": SCOPE_SKILLS_LIST,
    "/api/v1/external-tools": SCOPE_EXTERNAL_TOOLS_LIST,
}


def _required_scope_for_path(path: str) -> str:
    """按请求路径解析所需 scope；未登记的内部路径不做 scope 校验。"""
    text = str(path or "")
    best = ""
    for prefix, scope in SERVICE_SCOPE_REGISTRY.items():
        if text.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return SERVICE_SCOPE_REGISTRY.get(best, "")


def _incoming_service_issuer() -> Any:
    """惰性构建签发器（未配置新式凭据时返回 None → 回退静态比对）。"""
    if not hasattr(_incoming_service_issuer, "_cached"):
        from app.security import gatekeeper as _gk

        _incoming_service_issuer._cached = _gk.build_issuer_from_env(
            EXPECTED_CALLER_SERVICE_ID,
            extra_primary_names=_LEGACY_TOKEN_ENV_NAMES,
        )
    return _incoming_service_issuer._cached


async def require_api_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    service_token: str = Header(default="", alias="X-MOVO-Service-Token"),
) -> ApiPrincipal:
    settings = get_settings()
    tenant_hint = str(
        request.query_params.get("tenantId")
        or request.query_params.get("tenant_id")
        or ""
    )
    user_hint = str(
        request.query_params.get("userId")
        or request.query_params.get("user_id")
        or ""
    )

    # 022 T020：优先用新式签名令牌做双因子校验，未配置时回退静态比对。
    from app.security import gatekeeper as _gk

    try:
        claim = _gk.verify_service_call(
            str(service_token or ""),
            expected_service_id=EXPECTED_CALLER_SERVICE_ID,
            tenant_id=tenant_hint,
            user_id=user_hint,
            issuer=_incoming_service_issuer(),
            required_scope=_required_scope_for_path(str(request.url.path or "")),
        )
    except _gk.GatekeeperDenied as exc:
        raise HTTPException(status_code=401, detail=str(exc.reason)) from exc
    if claim is not None:
        tenant_id = resolve_tenant_id(str(claim.tenant_id or tenant_hint))
        return ApiPrincipal(kind="admin_service", tenant_id=tenant_id)

    expected_service_token = str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")
    if _matches(service_token, expected_service_token):
        tenant_id = resolve_tenant_id(tenant_hint)
        return ApiPrincipal(kind="admin_service", tenant_id=tenant_id)

    resolved = await resolve_session_user(authorization)
    principal = ApiPrincipal(
        kind="end_user",
        tenant_id=resolve_tenant_id(resolved["tenant_id"]),
        user_id=str(resolved["user"].get("_id") or ""),
    )
    await _assert_end_user_scope(request, principal)
    return principal


async def require_end_user_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> ApiPrincipal:
    resolved = await resolve_session_user(authorization)
    principal = ApiPrincipal(
        kind="end_user",
        tenant_id=resolve_tenant_id(resolved["tenant_id"]),
        user_id=str(resolved["user"].get("_id") or ""),
    )
    await _assert_end_user_scope(request, principal)
    return principal
