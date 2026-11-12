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

from .debate import clamp_rounds
from .graph import GraphError, VALID_MODES
from .registry import OrchestrationDefinition, RegistryError
from .round_robin import RoundRobinError, parse_instances


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
    # 044 multi-agent modes: declarative payload for round_robin / debate nodes.
    "instances",
    "select",
    "pro",
    "con",
    "arbiter",
    "max_rounds",
    "convergence_threshold",
    "similarity_threshold",
    # 050 human approval node: declarative payload (node *type*, not a mode).
    "type",
    "approver",
    "on_reject",
    "prompt",
    # 052 team mode: declarative payload for team nodes / document-level team.
    "members",
    "leader",
    "max_review_rounds",
    "max_reassign",
    "takeover",
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
    # A node may also nest these declarative keys inside ``payload:`` (the shape
    # used by the 044 multi-agent modes); the inner spelling wins only when the
    # top-level one is absent so the two readings stay unambiguous.
    inner = raw.get("payload")
    if isinstance(inner, Mapping):
        for key in _PAYLOAD_KEYS:
            if key not in payload and key in inner and inner[key] is not None:
                payload[key] = inner[key]

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


def _node_mode(raw: Mapping[str, Any]) -> str:
    return str(raw.get("mode") or "graph")


def _validate_044_shapes(
    mode: str,
    entries: list[dict[str, Any]],
    raw_nodes: list[Mapping[str, Any]],
    header: Mapping[str, Any],
) -> None:
    """Load-time, fail-closed shape checks for the 044 modes (FR-007 / R-1 / R-11).

    Runs *before* the definition is built so a bad declaration fails loudly with
    :class:`OrchestrationLoadError` instead of degrading at runtime.
    """
    from .dispatch import ROLE_ARBITER, ROLE_CON, ROLE_PRO

    node_ids = [str(entry.get("id")) for entry in entries]
    for entry, raw in zip(entries, raw_nodes):
        payload = entry.get("payload") or {}
        # A node that *inherits* the document mode is a plain candidate/role node
        # of that protocol, not a protocol node of its own; only an explicit
        # ``mode:`` on the node triggers the round_robin/debate shape checks.
        declared_mode = entry.get("mode")
        node_mode = declared_mode or mode
        if declared_mode is None:
            continue

        if node_mode == "round_robin":
            try:
                parse_instances(payload.get("instances"))
            except RoundRobinError as error:
                raise OrchestrationLoadError(f"node {entry.get('id')}: {error}") from error

        if node_mode == "debate":
            pro = str(payload.get("pro") or "").strip()
            con = str(payload.get("con") or "").strip()
            arbiter = str(payload.get("arbiter") or "").strip()
            if not pro or not con:
                raise OrchestrationLoadError(
                    f"node {entry.get('id')}: debate requires both 'pro' and 'con' node ids"
                )
            for role_id in (pro, con):
                if role_id not in node_ids:
                    raise OrchestrationLoadError(
                        f"node {entry.get('id')}: debate '{role_id}' is not a node of this orchestration"
                    )
            if arbiter and arbiter not in node_ids:
                raise OrchestrationLoadError(
                    f"node {entry.get('id')}: debate arbiter '{arbiter}' does not exist (fail-closed)"
                )
            if payload.get("max_rounds") is not None:
                try:
                    clamp_rounds(payload.get("max_rounds"))
                except Exception as error:  # noqa: BLE001
                    raise OrchestrationLoadError(
                        f"node {entry.get('id')}: invalid max_rounds: {error}"
                    ) from error

    if mode == "debate":
        roles = {
            str((raw.get("payload") or {}).get("role") or _node_mode(raw) or "")
            for raw in raw_nodes
        }
        has_pro = any(str((raw.get("payload") or {}).get("role") or "") == ROLE_PRO for raw in raw_nodes)
        has_con = any(str((raw.get("payload") or {}).get("role") or "") == ROLE_CON for raw in raw_nodes)
        declared_arbiter = str(header.get("arbiter") or "").strip()
        has_arbiter = any(str((raw.get("payload") or {}).get("role") or "") == ROLE_ARBITER for raw in raw_nodes)
        if not has_pro or not has_con:
            raise OrchestrationLoadError(
                "debate mode requires nodes tagged role=pro and role=con"
            )
        if declared_arbiter and not has_arbiter:
            raise OrchestrationLoadError(
                "debate declares an arbiter but no role=arbiter node exists (fail-closed)"
            )


def _validate_050_shapes(
    mode: str,
    entries: list[dict[str, Any]],
    raw_nodes: list[Mapping[str, Any]],
    edges: list[dict[str, str]],
) -> None:
    """Load-time fail-closed checks for ``type: human_approval`` nodes (050 FR-001).

    ``approver`` is required; ``on_reject`` must name an existing node that is a
    *direct dependent* of the approval node (otherwise the branch could run
    before the rejection happened); ``timeout`` is clamped to 60s..30d.

    Per 050 FR-001 / R-9, the first release only supports ``human_approval``
    nodes in ``graph`` mode: any other document mode declaring an approval node
    fails closed here at load time. A document with no approval node may use any
    mode (FR-009 keeps the existing non-graph paths untouched).
    """
    # R-9 graph-only restriction. ``_node_to_definition_entry`` folds both the
    # top-level and the nested ``payload:`` spellings of ``type`` into
    # ``entry["payload"]``, so reuse the same probe as the per-entry loop below.
    # The condition is deliberately an AND: only "has approval node AND non-graph"
    # is rejected, so approval-free non-graph documents still load unchanged.
    has_approval_node = any(
        str((entry.get("payload") or {}).get("type") or "") == "human_approval"
        for entry in entries
    )
    if has_approval_node and mode != "graph":
        raise OrchestrationLoadError(
            f"050 首期仅 graph 模式支持 human_approval 节点（当前 {mode!r}，fail-closed）"
        )

    node_ids = {str(entry.get("id")) for entry in entries}
    dependents: dict[str, set[str]] = {}
    for edge in edges:
        dependents.setdefault(str(edge.get("source")), set()).add(str(edge.get("target")))
    for raw in raw_nodes:
        target = str(raw.get("id") or "")
        deps = raw.get("depends_on") or []
        if isinstance(deps, str):
            deps = [deps]
        for dep in deps:
            dependents.setdefault(str(dep), set()).add(target)

    for entry in entries:
        payload = entry.get("payload") or {}
        if str(payload.get("type") or "") != "human_approval":
            continue
        node_id = str(entry.get("id"))
        approver = str(payload.get("approver") or "").strip()
        if not approver:
            raise OrchestrationLoadError(f"node {node_id}: human_approval requires an 'approver' (fail-closed)")
        on_reject = str(payload.get("on_reject") or "").strip()
        if on_reject:
            if on_reject not in node_ids:
                raise OrchestrationLoadError(
                    f"node {node_id}: on_reject target {on_reject!r} does not exist (fail-closed)"
                )
            if on_reject not in dependents.get(node_id, set()):
                raise OrchestrationLoadError(
                    f"node {node_id}: on_reject target {on_reject!r} must depend on the approval node"
                )
        if payload.get("timeout") is not None:
            try:
                seconds = int(payload["timeout"])
            except (TypeError, ValueError) as error:
                raise OrchestrationLoadError(
                    f"node {node_id}: human_approval timeout must be seconds, got {payload['timeout']!r}"
                ) from error
            # 钳制口径与 human_approval.clamp_timeout 一致（60s..30d，默认 24h）。
            payload["timeout"] = max(60, min(30 * 24 * 3600, seconds))


def _validate_052_shapes(
    mode: str,
    entries: list[dict[str, Any]],
    raw_nodes: list[Mapping[str, Any]],
    header: Mapping[str, Any],
) -> None:
    """Load-time fail-closed checks for the 052 ``team`` mode (FR-002 / FR-004).

    * document-level ``team`` requires member nodes (``members:`` naming the
      member node ids); a member reference to a non-existent node fails closed;
    * ``max_review_rounds`` / ``max_reassign`` are clamped (1..5 / 1..10) with
      the same clamp the runtime applies (044-style clamp-and-record);
    * a node that *declares* ``mode: team`` inside a graph is validated for its
      ``members`` payload the same way.
    """
    from .team import MAX_MAX_REVIEW_ROUNDS, MAX_MAX_REASSIGN, MIN_MAX_REVIEW_ROUNDS

    node_ids = {str(entry.get("id")) for entry in entries}

    def _check_team_payload(node_id: str, payload: Mapping[str, Any]) -> None:
        members = payload.get("members")
        if members is not None:
            if not isinstance(members, (list, tuple)) or not members:
                raise OrchestrationLoadError(
                    f"node {node_id}: team 'members' must be a non-empty list"
                )
            for member in members:
                member_id = str(member.get("id") or member) if isinstance(member, Mapping) else str(member)
                if member_id not in node_ids:
                    raise OrchestrationLoadError(
                        f"node {node_id}: team member {member_id!r} is not a node of this orchestration (fail-closed)"
                    )
        if payload.get("max_review_rounds") is not None:
            try:
                value = int(payload["max_review_rounds"])
            except (TypeError, ValueError) as error:
                raise OrchestrationLoadError(
                    f"node {node_id}: max_review_rounds must be an integer, got {payload['max_review_rounds']!r}"
                ) from error
            payload["max_review_rounds"] = max(MIN_MAX_REVIEW_ROUNDS, min(MAX_MAX_REVIEW_ROUNDS, value))
        if payload.get("max_reassign") is not None:
            try:
                value = int(payload["max_reassign"])
            except (TypeError, ValueError) as error:
                raise OrchestrationLoadError(
                    f"node {node_id}: max_reassign must be an integer, got {payload['max_reassign']!r}"
                ) from error
            payload["max_reassign"] = max(1, min(MAX_MAX_REASSIGN, value))
        takeover = payload.get("takeover")
        if takeover is not None:
            if not isinstance(takeover, Mapping):
                raise OrchestrationLoadError(
                    f"node {node_id}: team 'takeover' must be a mapping (trigger/approver)"
                )
            trigger = takeover.get("trigger")
            if trigger is not None and str(trigger) not in ("on_rework", "on_round_cap", "manual"):
                raise OrchestrationLoadError(
                    f"node {node_id}: team takeover.trigger must be one of on_rework/on_round_cap/manual, got {trigger!r}"
                )
            if not str(takeover.get("approver") or "").strip():
                raise OrchestrationLoadError(
                    f"node {node_id}: team takeover requires a non-empty 'approver'"
                )

    for entry, raw in zip(entries, raw_nodes):
        declared_mode = entry.get("mode")
        node_mode = declared_mode or mode
        if node_mode == "team":
            _check_team_payload(str(entry.get("id")), entry.get("payload") or {})

    if mode == "team":
        header_members = header.get("members")
        if header_members is not None:
            _check_team_payload("__orchestration__", {"members": header_members})


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
    if mode not in VALID_MODES:
        raise OrchestrationLoadError(
            f"unsupported orchestration mode: {mode!r} "
            f"(allowed: {', '.join(VALID_MODES)}; an undeclared mode still defaults to graph)"
        )
    _validate_044_shapes(mode, nodes, raw_nodes, header)
    _validate_050_shapes(mode, nodes, raw_nodes, edges)
    _validate_052_shapes(mode, nodes, raw_nodes, header)
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
