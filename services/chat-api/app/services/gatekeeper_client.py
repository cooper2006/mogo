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

# Keep this short: the gate sits on the hot path of every tool call.
DEFAULT_TIMEOUT_SECONDS = 5.0


class GateDeniedError(PermissionError):
    """Raised when the 001 chain (or its transport) does not allow the call."""

    def __init__(self, reason: str, *, layer: str = "", status_code: int = 403) -> None:
        super().__init__(reason)
        self.reason = reason
        self.layer = layer
        self.status_code = status_code


class GatekeeperClient:
    """HTTP client for ``POST /api/internal/gatekeeper/evaluate``."""

    def __init__(self, base_url: str = "", token: str = "", timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout = timeout

    def _resolve(self) -> tuple[str, str]:
        settings = get_settings()
        base_url = (self._base_url or str(settings.ADMIN_API_BASE_URL or "http://127.0.0.1:8100")).rstrip("/")
        token = self._token or str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")
        return base_url, token

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
        base_url, token = self._resolve()
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
