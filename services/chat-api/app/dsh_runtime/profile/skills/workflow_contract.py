"""Compile-time checks for adaptive Workflow Skill contracts."""

from __future__ import annotations

from typing import Any

from app.dsh_runtime.profile.tools import ToolProfileDefinition


def validate_node_identity(nodes: list[dict[str, Any]]) -> None:
    _require_unique(nodes, "id", "workflow node id")
    aliases = [
        str(node.get("outputAlias") or node.get("output_alias") or "").strip()
        for node in nodes
    ]
    populated = [value for value in aliases if value]
    if len(populated) != len(set(populated)):
        raise ValueError("workflow output aliases must be unique")


def validate_read_material_source(node: dict[str, Any]) -> None:
    if str(node.get("type") or "") != "read_material":
        return
    config = node.get("businessConfig") if isinstance(node.get("businessConfig"), dict) else {}
    source_type = str(config.get("sourceType") or "upload").strip()
    if source_type not in {"upload", "knowledge_document"}:
        raise ValueError("read_material sourceType is invalid")
    if source_type == "knowledge_document":
        if str(config.get("knowledgeScope") or "") not in {"personal", "organization"}:
            raise ValueError("read_material knowledgeScope is required")
        if not str(config.get("knowledgeSourceId") or "").strip():
            raise ValueError("read_material knowledgeSourceId is required")


def resolved_review_config(nodes: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """Resolve review inputs by stable upstream node ID; retain older text-only Skills."""
    node = nodes[index]
    config = node.get("businessConfig") if isinstance(node.get("businessConfig"), dict) else {}
    resolved = dict(config)
    if str(config.get("outputMode") or "report") not in {"report", "annotated_docx", "both"}:
        raise ValueError("review_check outputMode is invalid")
    mode = str(config.get("reviewCriteriaMode") or "").strip()
    refs = (("reviewSubjectNodeId", "reviewSubject"), ("reviewCriteriaNodeId", "reviewCriteria"))
    has_refs = any(str(config.get(id_key) or "").strip() for id_key, _ in refs)
    if not mode and not has_refs:
        if not all(str(config.get(label_key) or "").strip() for _, label_key in refs):
            raise ValueError("review_check requires a subject and criteria")
        return resolved
    if mode not in {"", "upstream", "inline"}:
        raise ValueError("review_check reviewCriteriaMode is invalid")
    upstream = {str(item.get("id") or ""): item for item in nodes[:index]}
    selected_refs = refs[:1] if mode == "inline" else refs
    for id_key, label_key in selected_refs:
        source_id = str(config.get(id_key) or "").strip()
        source = upstream.get(source_id)
        alias = str((source or {}).get("outputAlias") or (source or {}).get("output_alias") or "").strip()
        if not source_id or not alias:
            raise ValueError(f"review_check {id_key} must reference an upstream output with an alias")
        resolved[label_key] = alias
    if mode == "inline":
        if not str(config.get("reviewCriteria") or "").strip():
            raise ValueError("review_check inline criteria must not be empty")
        resolved.pop("reviewCriteriaNodeId", None)
    return resolved


def validate_external_bindings(node: dict[str, Any], tool: ToolProfileDefinition) -> None:
    config = node.get("businessConfig") if isinstance(node.get("businessConfig"), dict) else {}
    bindings = config.get("tool_arg_bindings") or config.get("toolArgBindings") or []
    if not isinstance(bindings, list):
        raise ValueError("workflow external tool bindings must be an array")
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    if schema.get("type") not in {None, "object"}:
        raise ValueError(f"workflow external tool requires an object input schema: {tool.name}")
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    names: list[str] = []
    for item in bindings:
        if not isinstance(item, dict):
            raise ValueError("workflow external tool binding must be an object")
        name = str(item.get("arg_name") or item.get("argName") or item.get("name") or "").strip()
        if not name:
            raise ValueError("workflow external tool binding has no argument name")
        names.append(name)
        if name not in properties and schema.get("additionalProperties") is False:
            raise ValueError(f"workflow binding is not declared by tool schema: {tool.name}.{name}")
    if len(names) != len(set(names)):
        raise ValueError(f"workflow has duplicate bindings for external tool: {tool.name}")


def _require_unique(nodes: list[dict[str, Any]], key: str, label: str) -> None:
    values = [str(node.get(key) or "").strip() for node in nodes]
    if any(not value for value in values):
        raise ValueError(f"{label} must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"{label}s must be unique")
