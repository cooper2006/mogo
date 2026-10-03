"""Rule-based entity / relation extraction for the knowledge graph (015 FR-1).

Extracts typed entities (person / organization / product / event) and typed
relations (membership / responsible / reference / association) from plain text
or a lightweight structured record. The rule path is **deterministic** — it does
not call an LLM and therefore does not fabricate entities; it only recognises
explicit textual patterns and structured fields.

The LLM-assisted path (when a model is available) is documented as a follow-up;
the rule path is sufficient for the first delivery (clarify OQ-2: schema is the
enterprise-generic set, extensible per domain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .schema import KgEdge, KgNode, ENTITY_TYPES, RELATION_TYPES, DEFAULT_CONFIDENCE_FLOOR


@dataclass
class ExtractionResult:
    """The output of a single extraction pass."""

    nodes: list[KgNode] = field(default_factory=list)
    edges: list[KgEdge] = field(default_factory=list)

    def add(self, node: KgNode) -> None:
        self.nodes.append(node)

    def link(self, source: str, target: str, relation: str = "association",
             confidence: float = 1.0) -> None:
        self.edges.append(KgEdge(source=source, target=target, relation=relation,
                                 confidence=confidence))

    def as_dicts(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "entity_type": n.entity_type,
                    "name": n.name,
                    "source_ref": n.source_ref,
                    "confidence": n.confidence,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "confidence": e.confidence,
                }
                for e in self.edges
            ],
        }


# ---------------------------------------------------------------------------
# Structured-record extraction (JSON / dict input)
# ---------------------------------------------------------------------------

# Map common structured fields to entity types.
_FIELD_TYPE_HINTS: dict[str, str] = {
    "person": "person",
    "owner": "person",
    "author": "person",
    "assigned_to": "person",
    "organization": "organization",
    "org": "organization",
    "department": "organization",
    "team": "organization",
    "company": "organization",
    "product": "product",
    "service": "product",
    "event": "event",
    "incident": "event",
}

# Relation fields → (relation_type, target_entity_type).
_REL_FIELD_MAP: list[tuple[str, str, str]] = [
    ("responsible_for", "responsible", "product"),
    ("references", "reference", "product"),
    ("related_to", "association", "product"),
    ("membership", "membership", "organization"),
]


def _slug(name: str, *, max_len: int = 48) -> str:
    """Deterministic slug for node ids: keep alnum + CJK, collapse separators."""
    import re as _re

    slug = _re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", str(name).lower()).strip("_")
    return slug[:max_len] or "unnamed"


def _make_node(record_nodes: list[KgNode], record_seen: set[str],
               key: str, entity_type: str, name: str, source_ref: str = "",
               node_id_prefix: str = "rec") -> str:
    node_id = f"{node_id_prefix}:{_slug(key)}"
    record_nodes.append(KgNode(node_id=node_id, entity_type=entity_type, name=name,
                               source_ref=source_ref, confidence=1.0))
    record_seen.add(node_id)
    return node_id


def extract_from_record(record: dict[str, Any], *, node_id_prefix: str = "rec") -> ExtractionResult:
    """Extract typed entities and relations from a structured record.

    * field keys that hint at entity types (``owner`` → person, ``department`` →
      organization, ``product`` → product, ``incident`` → event) become nodes;
    * a dict value (``{"id": ..., "name": ...}``) contributes ``id`` as
      ``source_ref`` (FR-13 pointer, no data copy);
    * relation fields (``responsible_for`` / ``references`` / ``related_to`` /
      ``membership``) become edges from the record's primary person/owner node.
    """
    result = ExtractionResult()
    record_nodes = result.nodes
    record_seen: set[str] = set()

    # Pass 1: direct entity fields.
    for key, value in record.items():
        if value in (None, "", []):
            continue
        hint = _FIELD_TYPE_HINTS.get(str(key).lower())
        if hint is None:
            continue
        if isinstance(value, dict):
            name = str(value.get("name") or value.get("id") or "").strip()
            source_ref = str(value.get("id") or value.get("entity_id") or "")
        else:
            name = str(value).strip()
            source_ref = ""
        if not name:
            continue
        _make_node(record_nodes, record_seen, str(key), hint, name,
                   source_ref=source_ref, node_id_prefix=node_id_prefix)

    # Pass 2: relation fields.
    for field_key, relation, target_type in _REL_FIELD_MAP:
        targets = record.get(field_key)
        if targets is None:
            continue
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            continue
        source_name = str(
            record.get("owner") or record.get("author") or record.get("person") or ""
        ).strip()
        if isinstance(record.get("owner"), dict):
            source_name = str(
                record["owner"].get("name") or record["owner"].get("id") or ""
            ).strip()
        if not source_name:
            continue
        src_id = f"{node_id_prefix}:{_slug('owner')}"
        if src_id not in record_seen:
            _make_node(record_nodes, record_seen, "owner", "person", source_name,
                      node_id_prefix=node_id_prefix)
        for target in targets:
            if isinstance(target, dict):
                t_name = str(target.get("name") or target.get("id") or "").strip()
                t_ref = str(target.get("id") or target.get("entity_id") or "")
            else:
                t_name = str(target).strip()
                t_ref = ""
            if not t_name:
                continue
            tgt_id = f"{node_id_prefix}:{_slug(t_name)}"
            if tgt_id not in record_seen:
                _make_node(record_nodes, record_seen, t_name, target_type, t_name,
                           source_ref=t_ref, node_id_prefix=node_id_prefix)
            result.link(src_id, tgt_id, relation=relation)

    return result


# ---------------------------------------------------------------------------
# Text extraction (regex patterns for explicit entity mentions)
# ---------------------------------------------------------------------------

# Patterns for entity type hints in free text.
_ORG_PATTERNS = (
    r"(?i)\borganization\b",
    r"(?i)\bcompany\b",
    r"(?i)\bdepartment\b",
    r"(?i)\bteam\b",
    r"组织", r"公司", r"部门",
)
_PERSON_PATTERNS = (
    r"(?i)\bowner\b",
    r"(?i)\bauthor\b",
    r"(?i)\bassigned\b",
    r"负责人", r"作者",
)
_PRODUCT_PATTERNS = (
    r"(?i)\bproduct\b",
    r"(?i)\bservice\b",
    r"产品",
)
_EVENT_PATTERNS = (
    r"(?i)\bincident\b",
    r"(?i)\bevent\b",
    r"事件",
)


def _named_entity_match(text: str, patterns: tuple[str, ...]) -> Optional[str]:
    """Return the token following a type keyword (supporting CJK + CJK punctuation)."""
    for pattern in patterns:
        match = re.search(pattern + r"\s*[=:：]\s*([A-Za-z0-9\u4e00-\u9fff_][\w\u4e00-\u9fff]*)", text)
        if match:
            return match.group(1).strip()
    return None


def extract_from_text(text: str, *, node_id_prefix: str = "txt") -> ExtractionResult:
    """Extract typed entities from a free-text snippet.

    Recognises patterns like ``owner: Alice`` → person node, ``company: ACME``
    → organization node. No LLM; purely regex-based.
    """
    result = ExtractionResult()
    seen: set[str] = set()

    def _add(entity_type: str, name: str) -> str:
        node_id = f"{node_id_prefix}:{entity_type}:{_slug(name)}"
        if node_id not in seen:
            result.add(KgNode(node_id=node_id, entity_type=entity_type, name=name,
                              source_ref="", confidence=0.8))
            seen.add(node_id)
        return node_id

    # Detect entity type + name pairs.
    for pattern_group, entity_type in (
        (_PERSON_PATTERNS, "person"),
        (_ORG_PATTERNS, "organization"),
        (_PRODUCT_PATTERNS, "product"),
        (_EVENT_PATTERNS, "event"),
    ):
        name = _named_entity_match(text, pattern_group)
        if name:
            _add(entity_type, name)

    # Detect responsible / reference relations via "owner X responsible for Y".
    resp_match = re.search(
        r"(?i)(owner|author|负责人|作者)\s*[=:：]\s*([A-Za-z0-9\u4e00-\u9fff_]+)\s+(?:responsible for|references|is associated with)\s+([A-Za-z0-9\u4e00-\u9fff_]+)",
        text,
    )
    if resp_match:
        src = _add("person", resp_match.group(2))
        tgt = _add("product", resp_match.group(3))
        result.link(src, tgt, "responsible")

    return result


# ---------------------------------------------------------------------------
# Convenience: auto-select the right path
# ---------------------------------------------------------------------------

def extract(record: Any, *, node_id_prefix: str = "") -> ExtractionResult:
    """Dispatch to the appropriate extraction path.

    * ``dict`` / ``list`` → :func:`extract_from_record`
    * ``str``             → :func:`extract_from_text`
    """
    if isinstance(record, dict):
        return extract_from_record(record, node_id_prefix=node_id_prefix or "rec")
    if isinstance(record, str):
        return extract_from_text(record, node_id_prefix=node_id_prefix or "txt")
    raise TypeError(f"unsupported record type: {type(record)!r}")


def apply_to_store(store: Any, record: Any, *, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR) -> dict[str, int]:
    """Extract entities/relations and write them into a ``KgStore``-compatible
    store (in-memory or ``TenantKgStore``).

    Returns ``{"nodes_added": n, "edges_added": m}``.
    """
    result = extract(record)
    nodes_added = 0
    edges_added = 0
    for node in result.nodes:
        if node.confidence >= confidence_floor and store.add_node(node):
            nodes_added += 1
    for edge in result.edges:
        if edge.confidence >= confidence_floor and store.add_edge(edge):
            edges_added += 1
    return {"nodes_added": nodes_added, "edges_added": edges_added}


__all__ = [
    "ExtractionResult",
    "extract",
    "extract_from_record",
    "extract_from_text",
    "apply_to_store",
]
