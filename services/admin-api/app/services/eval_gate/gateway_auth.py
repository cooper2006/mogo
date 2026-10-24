"""032-eval-gate: chat-api 模型网关的签名令牌签发。

chat-api 的 `/internal/dsh/model/generate` 只接受
`Authorization: Bearer <HMAC 令牌>`（见
`chat-api/app/dsh_runtime/model_gateway/token.py`），**不是**
`admin-api/app/security/service_token.py` 那套 `v1|<payload>|<mac>` 服务令牌。
两种令牌的密钥与结构都不同，混用会被网关 401 拒（spec R-12）。

算法与 chat-api 侧严格一致：`b64url(json(payload)) ".".join b64url(hmac_sha256(sha256(secret)))`，
payload 携带 `aud` / `tenant_id` / `profile_version` / `model_instance_id` / `iat` / `exp` / `jti`。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from app.core.config import settings

# chat-api `_validate_scope` 只接受这个 provider 与这个 aud。
GATEWAY_PROVIDER = "askai-model-gateway"
GATEWAY_AUDIENCE = "askai-model-gateway"
# chat-api 侧 `ModelGatewayTokenService(ttl_seconds=900)`。
TOKEN_TTL_SECONDS = 900
# chat-api 侧对 secret 长度的下限（`MIN_SECRET_LENGTH = 16`）。
MIN_SECRET_LENGTH = 16


def _resolve_secret() -> str:
    """共享密钥：优先网关专用变量，回落到两服务共享的 JWT secret。"""
    secret = str(settings.dsh_model_gateway_signing_secret or settings.jwt_secret or "")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            "模型网关签名密钥缺失或过短（至少 %d 字符）：请配置 "
            "ASKAI_ADMIN_DSH_MODEL_GATEWAY_SIGNING_SECRET，或与 chat-api 共享 "
            "ASKAI_ADMIN_JWT_SECRET" % MIN_SECRET_LENGTH
        )
    return secret


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _signing_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def issue_model_gateway_token(
    *,
    tenant_id: str,
    profile_version: str,
    model_instance_id: str,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> str:
    """签发一枚 chat-api 模型网关令牌（默认 900s 有效）。"""
    if not tenant_id or not profile_version or not model_instance_id:
        raise ValueError("tenant_id / profile_version / model_instance_id 均为必填")
    issued_at = int(time.time())
    payload: dict[str, Any] = {
        "aud": GATEWAY_AUDIENCE,
        "tenant_id": str(tenant_id),
        "profile_version": str(profile_version),
        "model_instance_id": str(model_instance_id),
        "iat": issued_at,
        "exp": issued_at + int(ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = hmac.new(_signing_key(_resolve_secret()), body, hashlib.sha256).digest()
    return f"{_b64url(body)}.{_b64url(signature)}"


def build_generate_request(
    *,
    prompt: str,
    model: str | None = None,
    profile_version: str | None = None,
    model_instance_id: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    """组装网关请求体，返回 `(body, profile_version, model_instance_id)`。

    `ModelGatewayRequest` 是 `extra="forbid"`，且 `_validate_scope` 要求
    `profileVersion` / `modelInstanceId` / `provider` 与令牌 claims 完全一致，
    所以三个字段必须由同一处推导（不能只发 model/messages）。
    """
    resolved_profile = str(profile_version or settings.eval_gate_profile_version or "eval-gate")
    resolved_instance = str(
        model_instance_id
        or settings.eval_gate_model_instance_id
        or model
        or "default"
    )
    body: dict[str, Any] = {
        "profileVersion": resolved_profile,
        "modelInstanceId": resolved_instance,
        "provider": GATEWAY_PROVIDER,
        "model": str(model or resolved_instance),
        "messages": [{"role": "user", "content": prompt}],
    }
    return body, resolved_profile, resolved_instance
