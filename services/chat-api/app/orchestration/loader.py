"""YAML loader for orchestration definitions (010 FR-8).

Orchestration definitions were previously only constructible from Python dicts.
Case documents (for example ``docs/cases/multi-agent-competitor-deep-dive.md``)
ship them as YAML, so this module maps that document shape onto the in-memory
``OrchestrationDefinition`` and reuses ``OrchestrationDefinition.validate()`` as
the single validation authority.

Accepted document shape::

    orchestration:
      id: competitor_deep_dive
      version: 1.0.0
      mode: graph
      max_concurrency: 4
      timeout: 1800
      retry: {max_attempts: 2, backoff: exponential, base_seconds: 5}

    nodes:
      - id: market_intel
        skill: market_intelligence_v1
        depends_on: []
        tools: [search_web]
        skip_condition:
          expr: "competitor_is_private == true"
          reason: "private company has no public financials"

The loader is deliberately tolerant about optional, purely descriptive keys
(``tools``, ``skill``, ``timeout``): they are preserved on the node payload so
runners can use them, but they never make a definition invalid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .graph import GraphError
from .registry import OrchestrationDefinition, RegistryError


class OrchestrationLoadError(ValueError):
    """Raised when a YAML orchestration document cannot be loaded."""


# Simple ``<var> <op> <literal>`` expressions, as written in the case documents
# (for example ``competitor_is_private == true``). The engine itself consumes a
# restricted JSON condition object, so the loader translates the human-readable
# spelling into that structure.
_EXPR_PATTERN = __import__("re").compile(
    r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_.]*)\s*"
    r"(?P<op>==|!=|>=|<=|>|<)\s*"
    r"(?P<literal>.+?)\s*$"
)


def _parse_literal(raw: str) -> Any:
    """Parse a YAML-ish scalar literal into a Python value."""
    text = raw.strip()
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_literal(part) for part in inner.split(",")]
    return text


def compile_expr(expr: str) -> dict[str, Any]:
    """Translate a case-document ``expr`` string into an engine condition object.

    ``"completed_children_count < 3"`` becomes
    ``{"op": "<", "left": {"var": "completed_children_count"}, "right": 3}``.

    Raises :class:`OrchestrationLoadError` for anything the restricted grammar
    cannot express, so a bad condition fails loudly at load time instead of
    silently evaluating to a constant at runtime.
    """
    match = _EXPR_PATTERN.match(str(expr or ""))
    if match is None:
        raise OrchestrationLoadError(
            f"unsupported skip_condition expression: {expr!r} "
            "(expected '<variable> <op> <literal>')"
        )
    variable = match.group("var")
    operator = match.group("op")
    literal = _parse_literal(match.group("literal"))
    engine_op = operator
    return {"op": engine_op, "left": {"var": variable}, "right": literal}


# Keys carried into ``nodes[].payload`` for the runner; they are declarative
# metadata rather than graph topology.
_PAYLOAD_KEYS = (
    "skill",
    "tools",
    "timeout",
    "description",
    "role",
    "output_key",
    "inputs",
    "outputs",
)


@dataclass
class LoadedOrchestration:
    """A definition plus the document-level settings a runner needs."""

    definition: OrchestrationDefinition
    mode: str
    max_concurrency: int | None = None
    timeout: int | None = None
    retry: Mapping[str, Any] = field(default_factory=dict)
    data_contract: Mapping[str, Any] = field(default_factory=dict)
    failure_propagation: Mapping[str, Any] = field(default_factory=dict)
    audit: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def orchestration_id(self) -> str:
        return self.definition.orchestration_id

    @property
    def node_ids(self) -> list[str]:
        return [str(node.get("id")) for node in self.definition.nodes]


def _require_mapping(value: Any, *, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrchestrationLoadError(f"{what} must be a mapping")
    return value


def _coerce_version(value: Any) -> int:
    """Definition versions are integers internally; YAML may carry semver strings."""
    if value is None:
        return 1
    if isinstance(value, bool):
        raise OrchestrationLoadError("orchestration version must be a number or semver string")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    # Semver such as "1.0.0": keep the major as the internal version number.
    head = text.split(".")[0]
    if head.isdigit():
        return int(head)
    raise OrchestrationLoadError(f"unrecognised orchestration version: {value!r}")


def _node_to_definition_entry(raw: Mapping[str, Any]) -> dict[str, Any]:
    node_id = str(raw.get("id") or "").strip()
    if not node_id:
        raise OrchestrationLoadError("every node requires an id")

    payload: dict[str, Any] = {}
    for key in _PAYLOAD_KEYS:
        if key in raw and raw[key] is not None:
            payload[key] = raw[key]

    entry: dict[str, Any] = {"id": node_id, "payload": payload}

    if raw.get("mode"):
        entry["mode"] = str(raw["mode"])

    # ``skip_condition`` is the case-document spelling of the engine's node
    # ``condition``. The two have **opposite polarity**: ``skip_condition`` runs
    # the node when the expression is FALSE, while the engine's ``condition``
    # runs it when TRUE. The loader therefore wraps the compiled expression in a
    # ``not`` so the document keeps its natural "skip when ..." reading.
    skip = raw.get("skip_condition")
    if skip is not None:
        if isinstance(skip, Mapping):
            expr = skip.get("expr")
            if not expr:
                raise OrchestrationLoadError(f"node {node_id}: skip_condition requires an expr")
            entry["condition"] = {"op": "not", "operand": compile_expr(str(expr))}
            if skip.get("reason"):
                payload["skip_reason"] = str(skip["reason"])
        elif isinstance(skip, str):
            entry["condition"] = {"op": "not", "operand": compile_expr(skip)}
        else:
            raise OrchestrationLoadError(f"node {node_id}: skip_condition must be a mapping or string")
    elif raw.get("condition") is not None:
        entry["condition"] = raw["condition"]

    if raw.get("retry") is not None:
        entry["retry"] = dict(_require_mapping(raw["retry"], what=f"node {node_id} retry"))

    if raw.get("output_key"):
        payload["output_key"] = str(raw["output_key"])

    return entry


def _edges_from_nodes(nodes: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Derive edges from ``depends_on`` (case-document style)."""
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in nodes:
        target = str(raw.get("id") or "").strip()
        dependencies = raw.get("depends_on") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not isinstance(dependencies, (list, tuple)):
            raise OrchestrationLoadError(f"node {target}: depends_on must be a list")
        for dependency in dependencies:
            source = str(dependency).strip()
            if not source:
                continue
            pair = (source, target)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append({"source": source, "target": target})
    return edges


def load_orchestration_document(document: Mapping[str, Any]) -> LoadedOrchestration:
    """Build a :class:`LoadedOrchestration` from a parsed YAML mapping."""
    doc = _require_mapping(document, what="orchestration document")

    header = _require_mapping(doc.get("orchestration") or {}, what="'orchestration' section")
    orchestration_id = str(header.get("id") or "").strip()
    if not orchestration_id:
        raise OrchestrationLoadError("'orchestration.id' is required")

    raw_nodes = doc.get("nodes") or []
    if not isinstance(raw_nodes, (list, tuple)):
        raise OrchestrationLoadError("'nodes' must be a list")
    if not raw_nodes:
        raise OrchestrationLoadError("'nodes' must not be empty")

    nodes = [_node_to_definition_entry(_require_mapping(n, what="node")) for n in raw_nodes]

    # Explicit edges win; otherwise derive them from depends_on.
    raw_edges = doc.get("edges")
    if raw_edges is None:
        edges = _edges_from_nodes([_require_mapping(n, what="node") for n in raw_nodes])
    else:
        if not isinstance(raw_edges, (list, tuple)):
            raise OrchestrationLoadError("'edges' must be a list")
        edges = []
        for raw_edge in raw_edges:
            edge = _require_mapping(raw_edge, what="edge")
            source = str(edge.get("source") or edge.get("from") or "").strip()
            target = str(edge.get("target") or edge.get("to") or "").strip()
            if not source or not target:
                raise OrchestrationLoadError("every edge requires source and target")
            edges.append({"source": source, "target": target})

    mode = str(header.get("mode") or "graph")
    definition = OrchestrationDefinition(
        orchestration_id=orchestration_id,
        mode=mode,
        nodes=nodes,
        edges=edges,
        version=_coerce_version(header.get("version")),
    )
    try:
        definition.validate()
    except (RegistryError, GraphError) as error:
        raise OrchestrationLoadError(f"invalid orchestration {orchestration_id!r}: {error}") from error

    max_concurrency = header.get("max_concurrency")
    return LoadedOrchestration(
        definition=definition,
        mode=mode,
        max_concurrency=int(max_concurrency) if max_concurrency is not None else None,
        timeout=int(header["timeout"]) if header.get("timeout") is not None else None,
        retry=dict(header.get("retry") or {}),
        data_contract=dict(doc.get("data_contract") or {}),
        failure_propagation=dict(doc.get("failure_propagation") or {}),
        audit=dict(doc.get("audit") or {}),
        raw=dict(doc),
    )


def load_orchestration_text(text: str) -> LoadedOrchestration:
    """Parse YAML text into a :class:`LoadedOrchestration`."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise OrchestrationLoadError(f"orchestration YAML is malformed: {error}") from error
    if not isinstance(document, Mapping):
        raise OrchestrationLoadError("orchestration YAML must contain a mapping at the top level")
    return load_orchestration_document(document)


def load_orchestration_file(path: str | Path) -> LoadedOrchestration:
    """Read and parse a YAML orchestration file from disk."""
    location = Path(path)
    if not location.is_file():
        raise OrchestrationLoadError(f"orchestration file not found: {location}")
    return load_orchestration_text(location.read_text(encoding="utf-8"))


def load_orchestration_directory(directory: str | Path) -> list[LoadedOrchestration]:
    """Load every ``*.yaml`` / ``*.yml`` orchestration in a directory (sorted)."""
    root = Path(directory)
    if not root.is_dir():
        raise OrchestrationLoadError(f"orchestration directory not found: {root}")
    loaded: list[LoadedOrchestration] = []
    for path in sorted(list(root.glob("*.yaml")) + list(root.glob("*.yml"))):
        loaded.append(load_orchestration_file(path))
    return loaded
