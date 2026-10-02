"""A2A agent gateway internal endpoints (feature 012).

Minimal production wiring: exposes the AgentCard lookup so external A2A
routers can discover MOVO agents. The inbound JSON-RPC surface and outbound
client integration are tracked as follow-ups (FR-2 / US2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.a2a.agent_card import AgentCard, AgentSkill

router = APIRouter(prefix="/internal/a2a", tags=["a2a-internal"])


@router.get("/agents/{agent_id}/card")
async def get_agent_card(
    agent_id: str,
    tenant_id: str = "default",
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Return the A2A AgentCard for an agent (FR-1 / FR-8).

    In the current design the card is assembled from the capability registry
    (018). The minimal wire returns a structural placeholder until 018 is wired.
    """
    from app.api.endpoints.auth import _resolve_session_user

    await _resolve_session_user(authorization)

    card = AgentCard(
        agent_id=agent_id,
        name=agent_id,
        tenant_id=tenant_id,
        skills=[AgentSkill(id="chat", name="Chat", description="MOVO chat capability")],
    )
    return {"code": 0, "message": "success", "data": card.as_dict()}


__all__ = ["router"]
