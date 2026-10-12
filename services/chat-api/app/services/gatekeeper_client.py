"""chat-api → admin-api 001 gatekeeper client (employee-side enforcement).

001's six-layer chain is implemented once in admin-api; the tool/Skill calls that
must pass it are executed here on behalf of employees. This client posts the call
context to admin-api's internal endpoint and enforces the verdict **fail-closed**:
a non-allow verdict, a timeout, or any transport/5xx error denies the call — the
same semantics 001 FR-3 and 009's ``fail_closed`` already declare.

The response also carries the (possibly) **redacted** request body back, so callers
can forward the sanitised body instead of the plaintext one (001 FR-7).
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.security import gatekeeper as _gk

# Keep this short: the gate sits on the hot path of every tool call.
DEFAULT_TIMEOUT_SECONDS = 5.0

#: 022 FR-12（T020）：本服务调用 admin-api 时声明的服务身份。
CALLER_SERVICE_ID = "chat-api"
LEGACY_TOKEN_ENV_NAMES = ("ADMIN_BACKEND_SERVICE_TOKEN",)


class GateDeniedError(PermissionError):
    """Raised when the 001 chain (or its transport) does not allow the call."""

    def __init__(self, reason: str, *, layer: str = "", status_code: int = 403) -> None:
        super().__init__(reason)
        self.reason = reason
        self.layer = layer
        self.status_code = status_code


def _shared_issuer() -> Any:
    """惰性构建签发器（未配置时返回 None）。"""
    if not hasattr(_shared_issuer, "_cached"):
        _shared_issuer._cached = _gk.build_issuer_from_env(
            CALLER_SERVICE_ID, extra_primary_names=LEGACY_TOKEN_ENV_NAMES
        )
    return _shared_issuer._cached


def issuer_is_signed(token: str) -> bool:
    """新式签名令牌形如 ``v1|payload|sig``（三段、首段为版本前缀）。"""
    parts = str(token or "").split("|")
    return len(parts) == 3 and parts[0] == "v1"


def _legacy_token() -> str:
    """回退：历史静态共享密钥。"""
    settings = get_settings()
    return str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")


def _issue_for_context(tenant_id: str, user_id: str) -> str:
    """按调用上下文签发令牌（租户/用户绑定进 claim，供双因子核对）。"""
    issuer = _shared_issuer()
    if issuer is None:
        return ""
    try:
        return issuer.issue(
            audience=CALLER_SERVICE_ID,
            tenant_id=str(tenant_id or ""),
            extra={"user_id": str(user_id or "")},
        )
    except Exception:  # noqa: BLE001 - 签发失败则回退静态密钥
        return ""


class GatekeeperClient:
    """HTTP client for ``POST /api/internal/gatekeeper/evaluate``."""

    def __init__(self, base_url: str = "", token: str = "", timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout = timeout

    def _resolve_base_url(self) -> str:
        settings = get_settings()
        return (self._base_url or str(settings.ADMIN_API_BASE_URL or "http://127.0.0.1:8100")).rstrip("/")

    def _issue_service_token(self, *, tenant_id: str = "", user_id: str = "") -> str:
        """022 T020：优先签发新式签名令牌，未配置时回退静态共享密钥。

        - 显式覆盖（``self._token``）始终优先 —— 便于测试与运维手工签发；
        - 新式令牌把调用方声明的租户/用户写进 claim，admin-api 侧据此做
          双因子核对（令牌绑定 + 租户/用户一致）。
        """
        if self._token:
            return self._token
        return _issue_for_context(tenant_id, user_id) or _legacy_token()

    async def evaluate(
        self,
        *,
        tool: str,
        tenant_id: str,
        user_id: str,
        roles: Optional[list[str]] = None,
        request: Optional[dict[str, Any]] = None,
        session_id: str = "",
        scope: str = "tool",
        approval_token: str = "",
        approval_action_id: str = "",
        harness_mode: str = "thick",
    ) -> dict[str, Any]:
        """Return the gate result; raise :class:`GateDeniedError` when not allowed.

        Fail-closed: any error reaching/understanding admin-api denies the call.
        """
        base_url = self._resolve_base_url()
        token = self._issue_service_token(tenant_id=tenant_id, user_id=user_id)
        payload = {
            "tool": tool,
            "tenantId": tenant_id,
            "userId": user_id,
            "roles": [str(r) for r in (roles or [])],
            "request": dict(request or {}),
            "sessionId": session_id,
            "scope": scope,
            "approvalToken": str(approval_token or ""),
            "approvalActionId": str(approval_action_id or ""),
            # 019: pass the per-request harness mode so the admin-api gatekeeper
            # can drop approval + quota layers in thin mode (T999, 2026-10-03).
            "harnessMode": str(harness_mode or "thick"),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{base_url}/api/internal/gatekeeper/evaluate",
                    json=payload,
                    headers={"X-MOVO-Service-Token": token},
                )
        except Exception as exc:  # transport / timeout -> fail closed
            raise GateDeniedError(f"门禁服务不可用（fail-closed）：{exc}") from exc

        if response.status_code >= 400:
            raise GateDeniedError(
                f"门禁服务返回 {response.status_code}（fail-closed）",
                status_code=response.status_code,
            )
        body = response.json()
        data = body.get("data", body) if isinstance(body, dict) else {}
        decision = str(data.get("decision") or "")
        if decision != "allow":
            raise GateDeniedError(
                str(data.get("reason") or "门禁拒绝"),
                layer=str(data.get("layer") or ""),
                status_code=int(data.get("statusCode") or 403),
            )
        return dict(data)


gatekeeper_client = GatekeeperClient()

__all__ = ["GatekeeperClient", "GateDeniedError", "gatekeeper_client", "DEFAULT_TIMEOUT_SECONDS"]
