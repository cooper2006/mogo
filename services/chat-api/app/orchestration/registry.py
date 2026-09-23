"""Orchestration definition registry (010 FR-8 / T003).

Orchestration definitions are declarative (nodes / edges / conditions / retry
config) and **versioned**: updating a definition bumps its version and keeps the
previous versions viewable (FR-8). The registry is the single source of truth for
"what orchestrations exist" and is DB-free here so the logic is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conditions import ConditionError, evaluate_condition
from .graph import Edge, Graph, GraphError, Node

DEFAULT_DEFINITION_VERSION = 1


class RegistryError(ValueError):
    """Raised for an invalid orchestration definition."""


@dataclass
class OrchestrationDefinition:
    """A versioned orchestration definition."""

    orchestration_id: str
    mode: str = "graph"
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    version: int = DEFAULT_DEFINITION_VERSION
    versions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.orchestration_id or "").strip():
            raise RegistryError("orchestration_id must not be empty")

    def to_graph(self) -> Graph:
        """Materialize the declarative definition into an executable ``Graph``."""
        graph = Graph()
        for raw in self.nodes:
            node_id = str(raw.get("id") or "").strip()
            if not node_id:
                raise RegistryError("node requires an id")
            graph.add_node(
                Node(
                    id=node_id,
                    mode=str(raw.get("mode") or self.mode),
                    condition=raw.get("condition"),
                    retry=raw.get("retry"),
                    payload=dict(raw.get("payload") or {}),
                )
            )
        for raw in self.edges:
            source = str(raw.get("source") or raw.get("from") or "").strip()
            target = str(raw.get("target") or raw.get("to") or "").strip()
            if not source or not target:
                raise RegistryError("edge requires source and target")
            graph.add_edge(Edge(source, target))
        return graph

    def validate(self) -> None:
        """Validate the definition: buildable graph and well-formed conditions.

        Raises ``RegistryError`` when a node/edge is invalid or a condition is
        malformed (fail-closed at definition time).
        """
        try:
            self.to_graph()
        except GraphError as error:
            raise RegistryError(str(error)) from error
        for raw in self.nodes:
            condition = raw.get("condition")
            if condition is None:
                continue
            try:
                evaluate_condition(condition, {})
            except ConditionError:
                # An unresolvable variable is fine at definition time; a malformed
                # operator/shape is not.
                if not _is_variable_error(condition):
                    raise RegistryError(f"invalid condition on node {raw.get('id')!r}")

    def update(
        self,
        *,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        mode: str | None = None,
    ) -> int:
        """Replace the definition content, bump the version, archive the old one.

        Returns the new version number.
        """
        self.versions.append(
            {
                "version": self.version,
                "mode": self.mode,
                "nodes": [dict(item) for item in self.nodes],
                "edges": [dict(item) for item in self.edges],
            }
        )
        if nodes is not None:
            self.nodes = [dict(item) for item in nodes]
        if edges is not None:
            self.edges = [dict(item) for item in edges]
        if mode is not None:
            self.mode = mode
        self.version += 1
        return self.version


def _is_variable_error(condition: Any) -> bool:
    """Whether a ``ConditionError`` was merely an unresolvable variable.

    Variables cannot be resolved at definition time (there is no runtime context),
    so those must not invalidate the definition.
    """
    try:
        evaluate_condition(condition, _PROBE_CONTEXT)
    except ConditionError as error:
        return "unresolved variable" in str(error)
    return False


_PROBE_CONTEXT: dict[str, Any] = {}


class OrchestrationRegistry:
    """In-memory registry of versioned orchestration definitions."""

    def __init__(self) -> None:
        self._definitions: dict[str, OrchestrationDefinition] = {}

    def register(self, definition: OrchestrationDefinition) -> OrchestrationDefinition:
        definition.validate()
        self._definitions[definition.orchestration_id] = definition
        return definition

    def get(self, orchestration_id: str) -> OrchestrationDefinition | None:
        return self._definitions.get(orchestration_id)

    def list_ids(self) -> list[str]:
        return sorted(self._definitions)

    def history(self, orchestration_id: str) -> list[dict[str, Any]]:
        """All archived versions of a definition (oldest first)."""
        definition = self._definitions.get(orchestration_id)
        return list(definition.versions) if definition else []

    def __len__(self) -> int:
        return len(self._definitions)
