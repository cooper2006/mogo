"""Business semantic index (feature 014).

Indexes business entities from source systems (CRM first) and answers semantic
queries with source attribution. Read-only: MOVO never writes back to the business
database.

This package holds the dependency-light core (entity model / source schema /
alignment), so it is unit-testable without a database or a live source system.
"""

from __future__ import annotations

from .entities import (
    ALIGNMENT_KEYS,
    ENTITY_TYPES,
    BizEntity,
    EntityError,
    align_key,
    align_pair,
)
from .alignment import (
    AlignmentGroup,
    AlignmentReport,
    align_entities,
    join_cross_system,
)
from .sources import (
    DEFAULT_PULL_INTERVAL,
    SourceSpec,
    SourceStatus,
    is_source_unavailable,
    mask_pii_fields,
)

__all__ = [
    "BizEntity",
    "EntityError",
    "ENTITY_TYPES",
    "ALIGNMENT_KEYS",
    "align_key",
    "align_pair",
    "SourceSpec",
    "SourceStatus",
    "DEFAULT_PULL_INTERVAL",
    "is_source_unavailable",
    "mask_pii_fields",
    "align_entities",
    "join_cross_system",
    "AlignmentGroup",
    "AlignmentReport",
]
