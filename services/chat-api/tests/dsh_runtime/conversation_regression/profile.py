from __future__ import annotations

from app.dsh_runtime.profile.skills.models import DshSkillDefinition
from app.dsh_runtime.profile.tools import ToolProfileCompiler, ToolProfileDefinition
from app.enterprise_capabilities.runtime import InternalCapabilityCatalog


class _NoExternalTools:
    async def list_enabled(self, tenant_id: str, user_id: str) -> list[dict]:
        return []


def _dynamic_tool(name: str, source_type: str) -> ToolProfileDefinition:
    return ToolProfileDefinition(
        name=name,
        version=f"regression-{name}-v1",
        source_type=source_type,
        external_tool_id=f"regression-{source_type}",
        mcp_tool_name="regression_lookup" if source_type == "mcp" else "",
        description=f"Deterministic {source_type.upper()} regression lookup.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "echo": {"type": "string"}},
            "required": ["success", "echo"],
            "additionalProperties": False,
        },
        output_validation="strict",
        risk_level="read",
        required_scopes=("tools:read",),
        timeout_ms=2_000,
    )


async def regression_tools() -> tuple[ToolProfileDefinition, ...]:
    compiled = await ToolProfileCompiler(
        _NoExternalTools(), InternalCapabilityCatalog()
    ).compile(tenant_id="tenant-regression", user_id="user-regression")
    required = {
        "external_search",
        "progressive_research",
        "knowledge_search",
        "content_production",
        "artifact_export",
        "document_transform",
    }
    selected = tuple(tool for tool in compiled if tool.name in required)
    assert {tool.name for tool in selected} == required
    return selected + (
        _dynamic_tool("askai_http_regression_lookup", "http"),
        _dynamic_tool("askai_mcp_regression_lookup", "mcp"),
    )


def regression_skill() -> DshSkillDefinition:
    return DshSkillDefinition(
        name="dsh-regression-skill",
        display_name="DSH 回归 Skill",
        version="regression-skill-v1",
        source_id="skill-regression-source",
        source_scope="personal",
        kind="ordinary",
        description="A deterministic Skill used only by the DSH conversation regression.",
        when_to_use="Only when explicitly selected by the regression turn.",
        content=(
            "SKILL_REGRESSION_INSTRUCTION: call askai_mcp_regression_lookup exactly once "
            "with value skill-marker, then answer from its receipt."
        ),
        capability_refs=("external.http_mcp@v1",),
    )
