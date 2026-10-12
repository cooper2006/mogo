"""服务间调用身份校验（022 FR-12 / T020）。

在 :mod:`app.security.service_token`（签名 + 有效期）之上补一层**双因子核对**：

1. 令牌的 ``service_id`` 必须与期望的服务一致 —— 防止 chat-api 的令牌被
   转发去访问 admin-api 的另一个服务身份；
2. 令牌携带 ``tenant_id`` 且调用方声明了租户时，两者必须一致 —— 防止
   跨租户调用（token 是租户 A 签发的，却去访问租户 B 的数据）。

失败语义：**fail-closed**。令牌签名/有效期/绑定任一不满足即抛异常。

兼容性：当服务尚未配置新式凭据（环境变量缺失或密钥过弱）时，
:func:`build_issuer_from_env` 返回 ``None``，调用方应回退到既有的静态共享
密钥比对（:func:`app.core.internal_service_auth.resolve_backend_service_token`），
保持灰度可回滚。
"""

from __future__ import annotations

import logging
from typing import Any

from app.security.service_token import (
    ServiceCredentialError,
    ServiceCredentialVault,
    ServiceTokenClaim,
    ServiceTokenExpired,
    ServiceTokenInvalid,
    ServiceTokenIssuer,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ENV_PREFIX",
    "DEFAULT_LEEWAY_SECONDS",
    "GatekeeperDenied",
    "bind_context_to_claim",
    "build_issuer_from_env",
    "verify_service_call",
]

DEFAULT_ENV_PREFIX = "MOGO"
DEFAULT_LEEWAY_SECONDS = 300


class GatekeeperDenied(PermissionError):
    """服务间调用被拒绝（签名、有效期或双因子绑定不满足）。"""

    def __init__(self, reason: str, *, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def build_issuer_from_env(
    service_id: str,
    *,
    env_prefix: str = DEFAULT_ENV_PREFIX,
    extra_primary_names: tuple[str, ...] = (),
    leeway_seconds: int = DEFAULT_LEEWAY_SECONDS,
    environ: Any = None,
) -> ServiceTokenIssuer | None:
    """从环境变量构建签发器；未配置或密钥过弱返回 ``None``。

    Args:
        extra_primary_names: 额外的主密钥环境变量名（按顺序回退）。
            用于保留 ``ADMIN_BACKEND_SERVICE_TOKEN`` 等历史命名。
    """
    from app.security.service_token import _normalize_secret

    environ_map = dict(environ or {})

    # 1) 规范命名（MOGO_{SID}_TOKEN / MOGO_SERVICE_TOKEN）
    try:
        vault = ServiceCredentialVault.from_env(
            service_id, env_prefix=env_prefix, environ=environ_map
        )
        return ServiceTokenIssuer(
            vault, service_id, leeway_seconds=leeway_seconds
        )
    except ServiceCredentialError:
        pass

    # 2) 历史命名回退（例如 ADMIN_BACKEND_SERVICE_TOKEN）
    for name in extra_primary_names:
        value = str(environ_map.get(name, "") or "").strip()
        if not value:
            continue
        try:
            secret = _normalize_secret(value)
        except ServiceCredentialError:
            continue
        previous = str(environ_map.get(f"{name}_PREVIOUS", "") or "").strip()
        previous_secret = ""
        if previous:
            try:
                previous_secret = _normalize_secret(previous)
            except ServiceCredentialError:
                previous_secret = ""
        vault = ServiceCredentialVault(secret, previous=previous_secret)
        return ServiceTokenIssuer(
            vault, service_id, leeway_seconds=leeway_seconds
        )

    logger.warning(
        "service credential unavailable for %s; falling back to legacy check",
        service_id,
    )
    return None


def verify_service_call(
    token: str,
    *,
    expected_service_id: str,
    tenant_id: str = "",
    user_id: str = "",
    issuer: ServiceTokenIssuer | None,
) -> ServiceTokenClaim | None:
    """双因子校验服务令牌。

    Args:
        token: HTTP 头里的原始令牌串。
        expected_service_id: 本服务期望的调用方身份（例如 ``"chat-api"``）。
        tenant_id: 调用方声明的租户；非空时与令牌内的 ``tenant_id`` 核对。
        user_id: 调用方声明的用户；非空时与令牌 ``extra["user_id"]`` 核对。
        issuer: 签发器；``None`` 表示本服务未启用新式凭据。

    Returns:
        校验通过的 claim；``None`` 表示未启用新式凭据（调用方回退旧逻辑）。

    Raises:
        GatekeeperDenied: 令牌非法、过期或双因子绑定不满足。
    """
    if issuer is None:
        return None
    if not token:
        raise GatekeeperDenied("missing_service_token")

    try:
        claim = issuer.verify(str(token))
    except ServiceTokenExpired as exc:
        raise GatekeeperDenied("expired_service_token", detail=str(exc)) from exc
    except ServiceTokenInvalid as exc:
        raise GatekeeperDenied("invalid_service_token", detail=str(exc)) from exc

    # 双因子 #1：service_id 绑定
    if claim.service_id != expected_service_id:
        raise GatekeeperDenied(
            "service_identity_mismatch",
            detail=f"expected={expected_service_id} got={claim.service_id}",
        )

    # 双因子 #2：tenant_id 绑定（令牌为空值时放行，兼容既有调用方）
    if tenant_id and claim.tenant_id and claim.tenant_id != tenant_id:
        raise GatekeeperDenied(
            "tenant_mismatch",
            detail=f"expected={tenant_id} got={claim.tenant_id}",
        )

    # 双因子 #3：user_id 绑定（同上，令牌为空值时放行）
    claimed_user = str(claim.extra.get("user_id") or "")
    if user_id and claimed_user and claimed_user != user_id:
        raise GatekeeperDenied(
            "user_mismatch",
            detail=f"expected={user_id} got={claimed_user}",
        )
    return claim


def bind_context_to_claim(
    claim: ServiceTokenClaim, *, tenant_id: str, user_id: str = ""
) -> ServiceTokenClaim:
    """把调用上下文回填到 claim（用于下游审计）。"""
    return ServiceTokenClaim(
        service_id=claim.service_id,
        exp=claim.exp,
        issued_at=claim.issued_at,
        jti=claim.jti,
        audience=claim.audience or tenant_id,
        tenant_id=claim.tenant_id or tenant_id,
        extra={**dict(claim.extra or {}), "user_id": str(user_id or "")},
    )
