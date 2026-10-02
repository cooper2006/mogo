"""Research orchestration endpoints (010 competitor deep-dive).

Exposes the ``competitor_deep_dive`` DAG orchestration as a real API so the
feature is no longer "core implemented but unreachable". The orchestrator's node
events are funneled into the 001 governance audit stream (FR-7) and the
definition is resolved from the ``dag_definitions`` collection (FR-8).

Sub-agents run through the real skill fast-path when a browser agent session is
connected; otherwise a node yields a structured "unavailable" payload and the run
degrades honestly (FR-6) instead of fabricating analyst output.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.enterprise_capabilities.research.competitor_deep_dive import (
    DeepDiveOrchestrator,
    SubAgentRunner,
)
from app.orchestration.graph import Node

router = APIRouter(dependencies=[Depends(require_end_user_principal)])


class CompetitorDeepDiveRequest(BaseModel):
    competitor_name: str = Field(min_length=1, max_length=160)
    our_product: str = Field(default="movo", max_length=80)
    industry: str = Field(default="", max_length=120)
    time_window: str = Field(default="last 12 months", max_length=80)
    depth: str = Field(default="deep", max_length=40)
    competitor_is_private: bool = False
    session_id: str = Field(default="", max_length=80)


async def _default_sub_agent(node: Node, context: dict[str, Any]) -> Any:
    """Run a graph node as a real skill via the connected browser agent.

    The node's ``skill`` payload names the skill; results are returned as the
    node output. When no agent session is connected the node reports
    "unavailable" so the orchestrator's degraded-report path engages (FR-6).
    """
    skill = str(node.payload.get("skill") or node.id)
    session_id = str(context.get("session_id") or "")
    if not session_id:
        return {"status": "unavailable", "skill": skill, "reason": "no agent session"}
    from app.browser.local_bridge import AgentNotConnected, LocalBridge

    bridge = LocalBridge(str(context.get("user_id") or ""), session_id)
    if not bridge.available():
        return {"status": "unavailable", "skill": skill, "reason": "agent not connected"}
    try:
        envelope = await bridge.execute(
            "browser_execute_workflow",
            {"skill": skill, "goal": str(context.get("competitor_name") or "")},
            domain="research",
            timeout=120.0,
        )
    except AgentNotConnected:
        return {"status": "unavailable", "skill": skill, "reason": "agent not connected"}
    if not isinstance(envelope, dict) or not bool(envelope.get("ok")):
        return {"status": "unavailable", "skill": skill, "reason": str(envelope.get("error") or "fast-path-failed")}
    result = envelope.get("result")
    return dict(result) if isinstance(result, dict) else {"status": "ok", "result": result}


@router.post("/research/competitor-deep-dive")
async def run_competitor_deep_dive(
    payload: CompetitorDeepDiveRequest,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> dict[str, Any]:
    from app.services.feature_audit_bridge import emit_feature_event

    orchestrator = await DeepDiveOrchestrator.create(
        audit_sink=emit_feature_event,
        tenant_id=principal.main_id,
        actor=principal.user_id,
    )

    async def runner(node: Node, context: dict[str, Any]) -> Any:
        context.setdefault("session_id", payload.session_id)
        context.setdefault("user_id", principal.user_id)
        return await _default_sub_agent(node, context)

    try:
        result = await orchestrator.run(
            competitor_name=payload.competitor_name,
            our_product=payload.our_product,
            industry=payload.industry,
            time_window=payload.time_window,
            depth=payload.depth,
            competitor_is_private=payload.competitor_is_private,
            initial_context={"session_id": payload.session_id, "user_id": principal.user_id},
        )
    except Exception as exc:  # noqa: BLE001 - surface as 502, audit already recorded
        raise HTTPException(status_code=502, detail=f"orchestration failed: {exc}") from exc

    return {
        "degraded": result.degraded,
        "report": result.research_report,
        "evidence": result.evidence,
        "node_states": {nid: o.state for nid, o in result.execution.outcomes.items()},
        "skipped_sections": result.skipped_sections,
    }
