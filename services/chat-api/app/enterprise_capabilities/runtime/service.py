from __future__ import annotations

from typing import Any

from app.llm.configured_models import get_model_config
from app.infrastructure.request_context import reset_request_context, set_request_context

from .contracts import CapabilityExecutionContext
from .registry import CapabilityHandlerRegistry


def _split_capability_ref(capability_ref: str) -> tuple[str, str]:
    """Split ``research.progressive@v1`` into (agent_id, skill_id) (035 T017).

    A capability ref names the deployed application (agent) and its skill/version;
    both become cost-attribution dimensions on every LLM call the capability makes.
    """
    ref = str(capability_ref or "").strip()
    if not ref:
        return "", ""
    if "@" in ref:
        agent, skill = ref.split("@", 1)
        return agent.strip(), skill.strip()
    return ref, ""


class InternalCapabilityService:
    def __init__(self, registry: CapabilityHandlerRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        capability_ref: str,
        arguments: dict[str, Any],
        context: CapabilityExecutionContext,
    ) -> dict[str, Any]:
        handler = self._registry.require(capability_ref)
        configured_model = None
        if context.model_instance_id:
            configured_model = await get_model_config(context.model_instance_id, context.tenant_id)
            if configured_model is None:
                raise LookupError("the capability's immutable model instance is unavailable")
        # 035 FR-003: seed the attribution dimensions for the whole capability
        # execution. ``factory.get_llm_client`` merges the request context into
        # every LLM call's output_spec, so these flow into TokenUsageRecord.
        agent_id, skill_id = _split_capability_ref(capability_ref)
        previous = set_request_context({
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "configured_model": configured_model or {},
            "agent_id": agent_id,
            "skill_id": skill_id,
        })
        try:
            result = await handler(dict(arguments), context)
        finally:
            reset_request_context(previous)
        if not isinstance(result, dict):
            raise TypeError(f"capability {capability_ref} returned a non-object result")
        return result
