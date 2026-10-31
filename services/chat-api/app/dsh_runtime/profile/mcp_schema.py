"""Normalize protocol-authored MCP schemas for the DSH JSON Schema subset.

MCP servers may publish full JSON Schema plus vendor extensions, while DSH
intentionally enforces a small, deterministic subset.  This module owns that
boundary: harmless metadata is removed, compatible constructs are projected,
and schemas that cannot be represented safely are rejected per MCP child tool.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unicodedata import normalize as unicode_normalize


DSH_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
ANNOTATIONS = {"description", "title", "default", "examples"}
IGNORABLE_METADATA = {"$schema", "$id", "$comment", "deprecated", "readOnly", "writeOnly"}
SERVER_ENFORCED_CONSTRAINTS = {
    "format", "pattern", "minLength", "maxLength", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems",
    "uniqueItems", "minProperties", "maxProperties", "propertyNames",
}


class McpSchemaCompatibilityError(ValueError):
    """Raised when an MCP schema cannot be represented by DSH without ambiguity."""


@dataclass(frozen=True)
class NormalizedMcpSchema:
    schema: dict[str, Any]
    removed_paths: tuple[str, ...] = ()


def normalize_mcp_schema(
    value: Any,
    *,
    object_root: bool,
    schema_name: str,
) -> NormalizedMcpSchema:
    """Return a DSH-compatible copy without mutating the discovered MCP schema.

    Constraints that the MCP server will still enforce but DSH cannot express
    are removed and reported. Structural constructs that cannot be translated
    losslessly reject only the affected MCP child tool.
    """

    if not isinstance(value, dict) or not value:
        schema = {"type": "object", "properties": {}, "additionalProperties": True} if object_root else {}
        return NormalizedMcpSchema(schema)

    root = deepcopy(value)
    removed: list[str] = []
    normalized = _normalize_node(root, root=root, path=schema_name, refs=(), removed=removed, depth=0)
    if object_root and normalized.get("type") != "object":
        raise McpSchemaCompatibilityError(f"{schema_name} must have an object root")
    return NormalizedMcpSchema(normalized, tuple(removed))


def _normalize_node(
    node: Any,
    *,
    root: dict[str, Any],
    path: str,
    refs: tuple[str, ...],
    removed: list[str],
    depth: int,
) -> dict[str, Any]:
    if depth > 64:
        raise McpSchemaCompatibilityError(f"{path} exceeds the maximum schema depth")
    if not isinstance(node, dict):
        raise McpSchemaCompatibilityError(f"{path} must be a schema object")

    if "$ref" in node:
        if len(node) != 1:
            raise McpSchemaCompatibilityError(f"{path} combines $ref with sibling keywords")
        reference = str(node["$ref"] or "")
        if not reference.startswith("#/"):
            raise McpSchemaCompatibilityError(f"{path} uses unsupported external $ref {reference!r}")
        if reference in refs:
            raise McpSchemaCompatibilityError(f"{path} contains a circular $ref")
        return _normalize_node(
            _resolve_local_ref(root, reference), root=root, path=path,
            refs=(*refs, reference), removed=removed, depth=depth + 1,
        )

    annotations: dict[str, Any] = {}
    for key in ANNOTATIONS:
        if key not in node:
            continue
        if key in {"description", "title"} and not isinstance(node[key], str):
            removed.append(f"{path}.{key}")
            continue
        annotations[key] = deepcopy(node[key])
    for key in node:
        key_path = f"{path}.{key}"
        canonical_key = unicode_normalize("NFKC", key)
        if key.startswith("x-") or canonical_key in IGNORABLE_METADATA or key in SERVER_ENFORCED_CONSTRAINTS or key in {"$defs", "definitions"}:
            removed.append(key_path)

    if "allOf" in node:
        branches = node.get("allOf")
        if not isinstance(branches, list) or len(branches) != 1:
            raise McpSchemaCompatibilityError(f"{path}.allOf cannot be represented by the DSH subset")
        base = _normalize_node(branches[0], root=root, path=f"{path}.allOf[0]", refs=refs, removed=removed, depth=depth + 1)
        return {**base, **annotations}

    union_key = "oneOf" if "oneOf" in node else "anyOf" if "anyOf" in node else ""
    if union_key:
        raw_branches = node.get(union_key)
        if not isinstance(raw_branches, list) or len(raw_branches) < 2:
            raise McpSchemaCompatibilityError(f"{path}.{union_key} must contain at least two schemas")
        branches = [
            _normalize_node(branch, root=root, path=f"{path}.{union_key}[{index}]", refs=refs, removed=removed, depth=depth + 1)
            for index, branch in enumerate(raw_branches)
        ]
        if union_key == "anyOf" and not _branches_are_disjoint(branches):
            raise McpSchemaCompatibilityError(f"{path}.anyOf overlaps and cannot be converted to exact-one oneOf")
        allowed_siblings = ANNOTATIONS | {union_key} | IGNORABLE_METADATA | SERVER_ENFORCED_CONSTRAINTS | {"$defs", "definitions"}
        _reject_unknown_keys(node, allowed_siblings, path)
        return {**annotations, "oneOf": branches}

    raw_type = node.get("type")
    if isinstance(raw_type, list):
        types = [str(item) for item in raw_type]
        if len(types) < 2 or len(types) != len(set(types)) or any(item not in DSH_TYPES for item in types):
            raise McpSchemaCompatibilityError(f"{path}.type contains an unsupported type union")
        branches = [
            _normalize_node(
                _schema_for_type_branch(node, item), root=root, path=f"{path}.type[{index}]",
                refs=refs, removed=removed, depth=depth + 1,
            )
            for index, item in enumerate(types)
        ]
        return {**annotations, "oneOf": branches}

    if raw_type is None:
        if any(key in node for key in ("properties", "required", "additionalProperties")):
            raw_type = "object"
        elif "items" in node:
            raw_type = "array"
        elif set(node).issubset(ANNOTATIONS | IGNORABLE_METADATA | SERVER_ENFORCED_CONSTRAINTS | {"$defs", "definitions"} | {key for key in node if key.startswith("x-")}):
            return annotations
        else:
            _reject_unknown_keys(node, ANNOTATIONS | IGNORABLE_METADATA | SERVER_ENFORCED_CONSTRAINTS | {"$defs", "definitions"}, path)
            return annotations
    raw_type = str(raw_type)
    if raw_type not in DSH_TYPES:
        raise McpSchemaCompatibilityError(f"{path}.type {raw_type!r} is unsupported")

    allowed = ANNOTATIONS | IGNORABLE_METADATA | SERVER_ENFORCED_CONSTRAINTS | {"type", "enum", "const", "$defs", "definitions"}
    result: dict[str, Any] = {**annotations, "type": raw_type}
    if raw_type == "object":
        if "enum" in node or "const" in node:
            raise McpSchemaCompatibilityError(f"{path} uses scalar enum/const on an object schema")
        allowed |= {"properties", "required", "additionalProperties"}
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            raise McpSchemaCompatibilityError(f"{path}.properties must be an object")
        result["properties"] = {
            str(name): _normalize_node(child, root=root, path=f"{path}.properties.{name}", refs=refs, removed=removed, depth=depth + 1)
            for name, child in properties.items()
        }
        required = node.get("required")
        if required is not None:
            if not isinstance(required, list) or any(not isinstance(item, str) or item not in result["properties"] for item in required):
                raise McpSchemaCompatibilityError(f"{path}.required must name declared properties")
            result["required"] = list(required)
        additional = node.get("additionalProperties")
        if additional is not None:
            if isinstance(additional, bool):
                result["additionalProperties"] = additional
            elif isinstance(additional, dict):
                # DSH only accepts a boolean here. Keep the dictionary shape
                # open; the MCP server remains authoritative for value checks.
                result["additionalProperties"] = True
                removed.append(f"{path}.additionalProperties")
            else:
                raise McpSchemaCompatibilityError(f"{path}.additionalProperties must be boolean or a schema")
    elif raw_type == "array":
        if "enum" in node or "const" in node:
            raise McpSchemaCompatibilityError(f"{path} uses scalar enum/const on an array schema")
        allowed.add("items")
        items = node.get("items")
        if items is not None:
            if isinstance(items, list):
                raise McpSchemaCompatibilityError(f"{path}.items tuple validation is unsupported")
            result["items"] = _normalize_node(items, root=root, path=f"{path}.items", refs=refs, removed=removed, depth=depth + 1)
    elif raw_type in {"string", "number", "integer", "boolean", "null"}:
        enum = node.get("enum")
        if "enum" in node:
            if not isinstance(enum, list) or not enum or any(not _scalar_matches(raw_type, item) for item in enum):
                raise McpSchemaCompatibilityError(f"{path}.enum contains values outside type {raw_type!r}")
            result["enum"] = deepcopy(enum)
        if "const" in node:
            declared = node.get("const")
            if not _scalar_matches(raw_type, declared):
                raise McpSchemaCompatibilityError(f"{path}.const is outside type {raw_type!r}")
            if enum is not None and declared not in enum:
                raise McpSchemaCompatibilityError(f"{path}.const is not included in enum")
            result["const"] = deepcopy(declared)

    _reject_unknown_keys(node, allowed | {key for key in node if key.startswith("x-")}, path)
    return result


def _resolve_local_ref(root: dict[str, Any], reference: str) -> Any:
    value: Any = root
    for token in reference[2:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise McpSchemaCompatibilityError(f"unresolved local $ref {reference!r}")
        value = value[key]
    return value


def _branches_are_disjoint(branches: list[dict[str, Any]]) -> bool:
    types = [branch.get("type") for branch in branches]
    return all(isinstance(item, str) for item in types) and len(types) == len(set(types))


def _schema_for_type_branch(node: dict[str, Any], schema_type: str) -> dict[str, Any]:
    common = {key: deepcopy(value) for key, value in node.items() if key in ANNOTATIONS or key in IGNORABLE_METADATA or key in SERVER_ENFORCED_CONSTRAINTS or key.startswith("x-")}
    common["type"] = schema_type
    if schema_type == "object":
        for key in ("properties", "required", "additionalProperties"):
            if key in node:
                common[key] = deepcopy(node[key])
    elif schema_type == "array" and "items" in node:
        common["items"] = deepcopy(node["items"])
    elif schema_type in {"string", "number", "integer", "boolean", "null"}:
        for key in ("enum", "const"):
            if key in node:
                common[key] = deepcopy(node[key])
    return common


def _scalar_matches(schema_type: str, value: Any) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return False


def _reject_unknown_keys(node: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = [
        key for key in node
        if key not in allowed
        and not key.startswith("x-")
        and unicode_normalize("NFKC", key) not in IGNORABLE_METADATA
    ]
    if unknown:
        raise McpSchemaCompatibilityError(f"{path}.{unknown[0]} is not supported by the DSH subset")


__all__ = ["McpSchemaCompatibilityError", "NormalizedMcpSchema", "normalize_mcp_schema"]
