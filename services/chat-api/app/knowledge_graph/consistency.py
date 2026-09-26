"""Consistency constraint checking (015 FR-6 / clarify OQ-4).

Three constraint kinds:

* **mutual exclusion** — an entity may not hold two conflicting attribute values
  (e.g. status = active AND status = archived);
* **transitivity** — A -> B and B -> C imply A -> C; a missing implied edge is a
  *gap* worth flagging;
* **cardinality** — a relation's endpoint count must stay within bounds.

Detected conflicts are **marked and kept queryable** — never blocked (FR-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .store import KgStore


class ConsistencyError(ValueError):
    """Raised for a malformed constraint definition."""


@dataclass
class Conflict:
    """A detected consistency conflict."""

    kind: str                     # mutual_exclusion | transitivity | cardinality
    subject: str
    detail: str = ""
    severity: str = "warning"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class MutualExclusion:
    """Conflicting attribute values on the same entity."""

    attribute: str
    conflicting_values: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.attribute or "").strip():
            raise ConsistencyError("mutual-exclusion rule needs an attribute")
        if len(self.conflicting_values) < 2:
            raise ConsistencyError("mutual-exclusion needs at least two values")


@dataclass
class CardinalityRule:
    """Bounds on how many endpoints a relation may connect."""

    relation: str
    min_count: int = 0
    max_count: int = 0            # 0 = unbounded

    def __post_init__(self) -> None:
        if not str(self.relation or "").strip():
            raise ConsistencyError("cardinality rule needs a relation")
        if self.max_count and self.max_count < self.min_count:
            raise ConsistencyError("max_count must be >= min_count")


def check_mutual_exclusions(
    store: KgStore, rules: list[MutualExclusion]
) -> list[Conflict]:
    """Flag entities holding conflicting values for a mutually-exclusive attribute."""
    conflicts: list[Conflict] = []
    for node in store.nodes.values():
        for rule in rules:
            value = node.attributes.get(rule.attribute)
            values = [str(item) for item in value] if isinstance(value, list) else ([str(value)] if value is not None else [])
            present = [item for item in values if item in rule.conflicting_values]
            if len(present) >= 2:
                conflicts.append(
                    Conflict(
                        kind="mutual_exclusion",
                        subject=node.node_id,
                        detail=f"属性 {rule.attribute} 同时为 {present}",
                    )
                )
    return conflicts


def check_transitivity(
    store: KgStore, *, relation: str
) -> list[Conflict]:
    """Flag missing implied edges A -> C where A -> B -> C (gap, not an error)."""
    gaps: list[Conflict] = []
    for node in store.nodes.values():
        for first in store.edges_of(node.node_id, relation=relation):
            middle = first.target
            for second in store.edges_of(middle, relation=relation):
                final = second.target
                if final == node.node_id:
                    continue  # cycles are handled elsewhere
                has_direct = any(
                    edge.target == final for edge in store.edges_of(node.node_id, relation=relation)
                )
                if not has_direct:
                    gaps.append(
                        Conflict(
                            kind="transitivity",
                            subject=node.node_id,
                            detail=f"缺 {node.node_id} -> {final}（经 {middle} 传递）",
                            severity="info",
                        )
                    )
    return gaps


def check_cardinality(store: KgStore, rules: list[CardinalityRule]) -> list[Conflict]:
    """Flag relations whose endpoint counts fall outside the configured bounds."""
    conflicts: list[Conflict] = []
    for rule in rules:
        for node in store.nodes.values():
            count = len(store.edges_of(node.node_id, relation=rule.relation))
            if count < rule.min_count:
                conflicts.append(
                    Conflict(
                        kind="cardinality",
                        subject=node.node_id,
                        detail=f"关系 {rule.relation} 数量 {count} < 最小 {rule.min_count}",
                    )
                )
            if rule.max_count and count > rule.max_count:
                conflicts.append(
                    Conflict(
                        kind="cardinality",
                        subject=node.node_id,
                        detail=f"关系 {rule.relation} 数量 {count} > 最大 {rule.max_count}",
                    )
                )
    return conflicts


@dataclass
class ConstraintBundle:
    """A configured set of consistency constraints."""

    mutual_exclusions: list[MutualExclusion] = field(default_factory=list)
    cardinality: list[CardinalityRule] = field(default_factory=list)
    transitive_relations: list[str] = field(default_factory=list)


def check_all(store: KgStore, bundle: ConstraintBundle) -> list[Conflict]:
    """Run every configured constraint, returning all conflicts (mark, not block)."""
    conflicts: list[Conflict] = []
    conflicts.extend(check_mutual_exclusions(store, bundle.mutual_exclusions))
    conflicts.extend(check_cardinality(store, bundle.cardinality))
    for relation in bundle.transitive_relations:
        conflicts.extend(check_transitivity(store, relation=relation))
    # T999: KG audited → 001 audit stream (015 kg.audited).
    _audit_kg_audited(conflicts)
    return conflicts


def mark_conflicts(store: KgStore, conflicts: list[Conflict]) -> None:
    """Mark the affected nodes as conflicted, keeping them queryable (FR-14)."""
    for conflict in conflicts:
        node = store.nodes.get(conflict.subject)
        if node is not None:
            node.conflicted = True


def _audit_kg_audited(conflicts: list[Conflict]) -> None:
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "015",
            "kg.audited",
            {
                "conflicts": len(conflicts),
                "subjects": [c.subject for c in conflicts[:5]],
            },
        )
    except Exception:
        # 审计失败绝不影响主流程。
        pass
