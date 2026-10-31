from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from app.dsh_runtime.profile.mcp_schema import McpSchemaCompatibilityError, normalize_mcp_schema
from app.dsh_runtime.profile.tools import ToolProfileCompiler


def test_fastmcp_vendor_metadata_is_removed_recursively() -> None:
    raw = {
        "type": "object",
        "properties": {"result": {"type": "string", "x-vendor-note": "wrapped"}},
        "required": ["result"],
        "x-fastmcp-wrap-result": True,
    }
    normalized = normalize_mcp_schema(raw, object_root=False, schema_name="outputSchema")

    assert normalized.schema == {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    assert normalized.removed_paths == (
        "outputSchema.x-fastmcp-wrap-result",
        "outputSchema.properties.result.x-vendor-note",
    )
    assert raw["x-fastmcp-wrap-result"] is True


def test_common_nullable_union_and_local_ref_are_projected() -> None:
    normalized = normalize_mcp_schema({
        "$defs": {"query": {"type": "string", "minLength": 1}},
        "type": "object",
        "properties": {
            "query": {"$ref": "#/$defs/query"},
            "limit": {"type": ["integer", "null"]},
        },
    }, object_root=True, schema_name="inputSchema")

    assert normalized.schema["properties"]["query"] == {"type": "string"}
    assert normalized.schema["properties"]["limit"] == {
        "oneOf": [{"type": "integer"}, {"type": "null"}],
    }
    assert "inputSchema.$defs" in normalized.removed_paths
    assert "inputSchema.properties.query.minLength" in normalized.removed_paths


def test_server_enforced_dictionary_constraints_do_not_break_profile() -> None:
    normalized = normalize_mcp_schema({
        "＄schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
    }, object_root=True, schema_name="inputSchema")

    assert normalized.schema["properties"]["filters"]["additionalProperties"] is True
    assert "inputSchema.＄schema" in normalized.removed_paths
    assert "inputSchema.properties.filters.additionalProperties" in normalized.removed_paths


def test_ambiguous_structural_schema_is_rejected() -> None:
    with pytest.raises(McpSchemaCompatibilityError, match="allOf"):
        normalize_mcp_schema({
            "allOf": [{"type": "object"}, {"type": "object"}],
        }, object_root=True, schema_name="inputSchema")


def test_one_incompatible_mcp_child_does_not_break_other_tools(caplog) -> None:
    class Catalog:
        async def list_enabled(self, _tenant_id: str, _user_id: str):
            return deepcopy([{
                "id": "mcp-deepwiki",
                "name": "DeepWiki",
                "type": "mcp",
                "description": "Public MCP",
                "config": {},
                "discoveredTools": [
                    {
                        "name": "ask_question",
                        "description": "Ask a question",
                        "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}},
                        "outputSchema": {
                            "type": "object",
                            "properties": {"result": {"type": "string"}},
                            "required": ["result"],
                            "x-fastmcp-wrap-result": True,
                        },
                    },
                    {
                        "name": "broken_tool",
                        "description": "Cannot be represented safely",
                        "inputSchema": {"allOf": [{"type": "object"}, {"type": "object"}]},
                    },
                    {
                        "name": "x" * 300,
                        "description": "Invalid MCP protocol name must be isolated",
                        "inputSchema": {"type": "object"},
                    },
                ],
            }, {
                "id": "http-health",
                "name": "Health",
                "type": "http",
                "description": "Health check",
                "config": {"method": "GET"},
                "inputSchema": [],
            }])

    tools = asyncio.run(ToolProfileCompiler(Catalog()).compile(tenant_id="tenant-a", user_id="user-a"))

    assert {tool.external_tool_id for tool in tools} == {"mcp-deepwiki", "http-health"}
    deepwiki = next(tool for tool in tools if tool.mcp_tool_name == "ask_question")
    assert "x-fastmcp-wrap-result" not in deepwiki.output_schema
    assert "mcp_tool_schema_incompatible" in caplog.text
    assert "broken_tool" in caplog.text
    assert "mcp_tool_profile_invalid" in caplog.text
