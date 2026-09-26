"""Business entity model + cross-system alignment (014 FR-1 / FR-3 / FR-5 / FR-6).

Entity types (clarify OQ-2): customer / order / supplier / account. Each carries
its source system and a source-attribution triple (system, entity type, record id,
FR-3). Cross-system alignment uses per-type business keys; when two systems disagree
the entities are marked **unaligned** rather than the query being refused (FR-6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ENTITY_TYPES: tuple[str, ...] = ("customer", "order", "supplier", "account")

# Business key used to align the same entity across systems (clarify OQ-2).
ALIGNMENT_KEYS: dict[str, str] = {
    "customer": "customer_code",
    "order": "order_no",
    "supplier": "supplier_code",
    "account": "account_period",
}

# PII fields masked before indexing (via 001 policy, FR-10).
PII_FIELDS: frozenset[str] = frozenset({"phone", "id_card", "mobile", "email"})


class EntityError(ValueError):
    """Raised for an invalid business entity."""


@dataclass
class BizEntity:
    """A business entity staged for indexing."""

    entity_type: str
    source_system: str
    record_id: str
    fields: dict[str, Any] = field(default_factory=dict)
    aligned: bool = True
    tenant_id: str = "default"

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise EntityError(f"unknown entity type: {self.entity_type!r}")
        if not str(self.source_system or "").strip():
            raise EntityError("source_system must not be empty")
        if not str(self.record_id or "").strip():
            raise EntityError("record_id must not be empty")
        # T999: entity indexed → 001 audit stream (014 entity.indexed).
        _audit_entity_indexed(self)

    def align_key(self) -> Optional[str]:
        """The business key value used for cross-system alignment."""
        key_name = ALIGNMENT_KEYS.get(self.entity_type, "")
        value = self.fields.get(key_name)
        return str(value) if value not in (None, "") else None

    def source_attribution(self) -> dict[str, str]:
        """The three-level source attribution (FR-3)."""
        return {
            "sourceSystem": self.source_system,
            "entityType": self.entity_type,
            "recordId": self.record_id,
        }


def align_key(entity: BizEntity) -> Optional[str]:
    return entity.align_key()


def align_pair(left: BizEntity, right: BizEntity) -> bool:
    """Whether two entities from different systems refer to the same business object.

    Returns False (and marks both unaligned) when either side has no align key or
    the keys differ — the caller then reports "unaligned" rather than refusing the
    cross-system query (FR-6).
    """
    if left.entity_type != right.entity_type:
        left.aligned = right.aligned = False
        return False
    left_key, right_key = left.align_key(), right.align_key()
    if not left_key or not right_key or left_key != right_key:
        left.aligned = right.aligned = False
        return False
    return True


def _audit_entity_indexed(entity: BizEntity) -> None:
    """T999: entity indexed → 001 audit stream (014 entity.indexed)."""
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "014",
            "entity.indexed",
            {
                "entity_type": entity.entity_type,
                "record_id": entity.record_id,
                "source_system": entity.source_system,
                "tenant_id": entity.tenant_id,
            },
        )
    except Exception:
        # 审计失败绝不影响主流程（构造仍成功；索引/对齐行为不变）。
        pass
