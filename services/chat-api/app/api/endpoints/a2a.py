"""A2A agent gateway internal endpoints (feature 012).

Production wiring:
* AgentCard lookup so external A2A routers can discover MOVO agents (FR-1 / FR-8);
* inbound JSON-RPC surface (FR-2 / FR-10): ``message/send`` / ``tasks/get`` /
  ``tasks/result`` with task-id idempotency;
* governance denial is mapped to a JSON-RPC error (FR-7) via
  ``rpc_error_from_denial``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from app.a2a.protocol import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    TaskLifecycle,
    SUPPORTED_METHODS,
    ERROR_METHOD_NOT_FOUND,
    ERROR_INVALID_PARAMS,
    rpc_error_from_denial,
)

router = APIRouter(prefix="/internal/a2a", tags=["a2a-internal"])

# Module-level task lifecycle (in-memory; FR-10 idempotency).
_lifecycle = TaskLifecycle()


@router.get("/agents/{agent_id}/card")
async def get_agent_card(
    agent_id: str,
    tenant_id: str = "default",
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Return the A2A AgentCard for an agent (FR-1 / FR-8 / FR-12).

    The card is assembled from the 018 capability registry: only assets
    explicitly marked ``a2a_exposed`` produce a card (018 FR-12 / 012 FR-11).
    When the registry is unreachable the endpoint fails honestly with 503 —
    it never fabricates a placeholder card.
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.a2a.agent_card import build_agent_card
    from app.core.db import get_db

    await _resolve_session_user(authorization)

    try:
        db = get_db()
        rows = await db["capability_assets"].find({"a2a_exposed": True}).to_list(length=500)
    except Exception:
        raise HTTPException(status_code=503, detail="capability_registry_unavailable")

    if not rows:
        raise HTTPException(status_code=404, detail="no_a2a_exposed_capability")

    skills = [
        {
            "id": str(row.get("key") or row.get("asset_id") or ""),
            "name": str(row.get("display_name") or row.get("name") or ""),
            "description": str(row.get("endpoint") or ""),
        }
        for row in rows
        if str(row.get("key") or row.get("asset_id") or "").strip()
    ]
    card = build_agent_card(
        agent_id=agent_id,
        name=str(agent_id),
        tenant_id=tenant_id,
        capabilities=skills,
        a2a_exposed=True,
    )
    if card is None:  # unreachable: a2a_exposed=True was queried above.
        raise HTTPException(status_code=404, detail="no_a2a_exposed_capability")
    return {"code": 0, "message": "success", "data": card.as_dict()}


# ---------------------------------------------------------------------------
# FR-2 / FR-10: inbound JSON-RPC surface (message/send, tasks/get, tasks/result)
# ---------------------------------------------------------------------------


@router.post("/rpc")
async def a2a_jsonrpc(
    payload: dict[str, Any] = Body(...),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """A2A JSON-RPC entry point (FR-2 / FR-10).

    Supported methods: ``message/send`` (FR-2 dispatch), ``tasks/get``
    (task status), ``tasks/result`` (task result). Unknown methods return
    ``ERROR_METHOD_NOT_FOUND`` (FR-2 / FR-7).
    """
    from app.api.endpoints.auth import _resolve_session_user

    await _resolve_session_user(authorization)

    # Parse the request.
    method = str(payload.get("method") or "")
    rpc_id = payload.get("id")
    params = payload.get("params") or {}

    if method not in SUPPORTED_METHODS:
        error = JsonRpcError(
            ERROR_METHOD_NOT_FOUND,
            f"unsupported method: {method}",
        )
        return JsonRpcResponse(id=rpc_id, error=error).as_dict()

    if not isinstance(params, dict):
        error = JsonRpcError(ERROR_INVALID_PARAMS, "params must be an object")
        return JsonRpcResponse(id=rpc_id, error=error).as_dict()

    # Build a validated request.
    request = JsonRpcRequest(
        method=method,
        params=params,
        id=rpc_id,
        jsonrpc=str(payload.get("jsonrpc") or "2.0"),
    )
    validation_error = request.validate()
    if validation_error is not None:
        return JsonRpcResponse(id=rpc_id, error=validation_error).as_dict()

    # Dispatch by method.
    if method == "message/send":
        task_id = str(params.get("taskId") or params.get("task_id") or "")
        if not task_id:
            error = JsonRpcError(ERROR_INVALID_PARAMS, "taskId is required for message/send")
            return JsonRpcResponse(id=rpc_id, error=error).as_dict()
        task, created = _lifecycle.submit(task_id, payload=params)
        if created:
            _lifecycle.set_state(task_id, "working")
        return JsonRpcResponse(
            id=rpc_id,
            result={"taskId": task_id, "state": task["state"], "created": created},
        ).as_dict()

    elif method == "tasks/get":
        task_id = str(params.get("taskId") or params.get("task_id") or "")
        task = _lifecycle.get(task_id)
        if task is None:
            error = JsonRpcError(ERROR_INVALID_PARAMS, f"unknown task: {task_id}")
            return JsonRpcResponse(id=rpc_id, error=error).as_dict()
        return JsonRpcResponse(
            id=rpc_id,
            result={"id": task["id"], "state": task["state"]},
        ).as_dict()

    elif method == "tasks/result":
        task_id = str(params.get("taskId") or params.get("task_id") or "")
        result = _lifecycle.result(task_id)
        if result is None:
            error = JsonRpcError(ERROR_INVALID_PARAMS, f"unknown task: {task_id}")
            return JsonRpcResponse(id=rpc_id, error=error).as_dict()
        return JsonRpcResponse(id=rpc_id, result=result).as_dict()

    # Unreachable: SUPPORTED_METHODS is checked above.
    return JsonRpcResponse(id=rpc_id, error=JsonRpcError(ERROR_METHOD_NOT_FOUND, method)).as_dict()


# ---------------------------------------------------------------------------
# FR-6: outbound call entry (MOVO -> external agent), gated by the 001 chain
# ---------------------------------------------------------------------------


@router.post("/outbound")
async def a2a_outbound(
    payload: dict[str, Any] = Body(...),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Outbound A2A ``message/send`` (012 US2 / FR-6 / T009).

    Gated through the 001 chain before any fetch (fail-closed on denial);
    the destination is resolved only from the server-owned
    ``A2A_OUTBOUND_AGENTS`` setting (SSRF: no model/user-selected URL).
    """
    from app.api.endpoints.auth import _resolve_session_user
    from app.a2a.outbound import agent_endpoints, call_external_agent

    identity = await _resolve_session_user(authorization)

    agent = str(payload.get("agent") or "")
    text = str(payload.get("text") or "")
    if not agent or not text:
        raise HTTPException(status_code=400, detail="agent and text are required")
    if agent not in agent_endpoints():
        raise HTTPException(status_code=404, detail="a2a_agent_not_configured")

    user = dict(identity or {}).get("user") or {}
    user_id = str(user.get("_id") or user.get("id") or "")
    tenant_id = str(dict(identity or {}).get("main_id") or "default")

    try:
        result = await call_external_agent(
            agent=agent,
            text=text,
            tenant_id=tenant_id,
            user_id=user_id,
            main_id=tenant_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"a2a_denied: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — transport/gate failures are surfaced honestly
        raise HTTPException(status_code=502, detail=f"a2a_outbound_failed: {exc}")

    return {"code": 0, "message": "success", "data": result}
