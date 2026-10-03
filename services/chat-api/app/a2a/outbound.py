"""Outbound A2A entry point — production wiring (012 T009 / FR-6 / US2).

Gates every outbound A2A call through the 001 governance layer, then invokes
the external agent through ``A2AClient`` (007 retry/failover, US2 错误码映射)
with an httpx JSON-RPC transport.

**SSRF guard**: outbound URLs come only from the server-owned
``A2A_OUTBOUND_AGENTS`` setting — model/user-supplied input never selects a
fetch URL; an unconfigured agent fails closed with an error, never a fetch.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.a2a.client import A2AClient, ClientConfig, OutboundCall
from app.a2a.protocol import (
    JsonRpcError,
    JsonRpcResponse,
    METHOD_MESSAGE_SEND,
    ERROR_MOVO_DENIED,
    rpc_error_from_denial,
)

GATE_TOOL = "a2a.outbound"


def agent_endpoints() -> dict[str, str]:
    """Server-owned agent name -> JSON-RPC endpoint map (SSRF-safe source)."""
    from app.core.config import get_settings

    raw = str(getattr(get_settings(), "A2A_OUTBOUND_AGENTS", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def build_transport(timeout_seconds: float = 30.0):
    """Async httpx JSON-RPC transport bound to configured endpoints only."""
    import httpx

    endpoints = agent_endpoints()

    async def _transport(
        agent_name: str, method: str, params: dict[str, Any], timeout: float
    ) -> JsonRpcResponse:
        url = endpoints.get(str(agent_name))
        if not url:
            # Fail closed: never substitute a model-supplied URL (SSRF).
            raise ValueError(f"a2a agent not configured: {agent_name}")
        async with httpx.AsyncClient(timeout=timeout or timeout_seconds) as client:
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if int(response.status_code) >= 400:
            return JsonRpcResponse(
                id=body.get("id"),
                error=JsonRpcError(-32603, f"transport status {response.status_code}"),
            )
        return JsonRpcResponse(
            id=body.get("id"),
            result=dict(body.get("result") or {}),
            error=_as_error(body.get("error")),
        )

    return _transport


def _as_error(raw: Any) -> Optional[JsonRpcError]:
    if not isinstance(raw, dict):
        return None
    try:
        return JsonRpcError(int(raw.get("code", -32603)), str(raw.get("message") or ""))
    except (TypeError, ValueError):
        return None


async def call_external_agent(
    *,
    agent: str,
    text: str,
    tenant_id: str,
    user_id: str,
    main_id: str = "default",
) -> dict[str, Any]:
    """001-gated outbound A2A ``message/send`` (012 FR-6 / FR-3).

    Raises ``PermissionError`` (fail-closed) when the 001 chain denies, and
    ``ValueError`` when the agent is not configured server-side.
    """
    from app.dsh_runtime.turn_admission import run_gate_plan

    endpoints = agent_endpoints()
    if agent not in endpoints:
        raise ValueError(f"a2a agent not configured: {agent}")

    # 001: outbound calls are governed entry points — gate before any fetch.
    await run_gate_plan(
        tenant_id=tenant_id,
        user_id=user_id,
        tool=GATE_TOOL,
        request={"agent": agent, "main_id": main_id},
    )

    client = A2AClient(build_transport(), ClientConfig(primary_agent=agent))
    call: OutboundCall = await client.send(
        {"text": text, "taskId": f"a2a-{user_id}-{agent}"},
        method=METHOD_MESSAGE_SEND,
    )
    if call.error is not None:
        from app.a2a.client import map_error_code
        if call.error.code == ERROR_MOVO_DENIED:
            raise PermissionError(call.error.message)
        raise RuntimeError(f"outbound a2a failed: {call.error.message}")
    return call.as_dict()


__all__ = [
    "GATE_TOOL",
    "agent_endpoints",
    "build_transport",
    "call_external_agent",
]
