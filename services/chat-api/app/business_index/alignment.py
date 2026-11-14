"""Cross-system entity alignment (014 FR-5 / FR-6 / T010).

Aligns the same business object across systems (CRM / procurement / finance) by
its **business key** (customer code, order no, ...). Systems that agree join one
aligned group; systems that disagree are reported as an **unaligned** set — the
cross-system query still returns per-system results rather than being refused
(FR-6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .entities import BizEntity


@dataclass
class AlignmentGroup:
    """Entities from different systems recognised as the same business object."""

    entity_type: str
    align_key: str
    entities: list[BizEntity] = field(default_factory=list)

    @property
    def systems(self) -> list[str]:
        return sorted({entity.source_system for entity in self.entities})

    @property
    def is_cross_system(self) -> bool:
        return len(self.systems) > 1


@dataclass
class AlignmentReport:
    """Outcome of aligning a batch of entities."""

    groups: list[AlignmentGroup] = field(default_factory=list)
    unaligned: list[BizEntity] = field(default_factory=list)

    @property
    def cross_system_groups(self) -> list[AlignmentGroup]:
        return [group for group in self.groups if group.is_cross_system]


def align_entities(entities: Iterable[BizEntity]) -> AlignmentReport:
    """Group entities by (entity type, business key).

    * entities that share a key form one aligned group (cross-system if they come
      from more than one system);
    * entities with **no** align key, or whose key is shared by a *different*
      entity type, are reported as unaligned.
    """
    report = AlignmentReport()
    buckets: dict[tuple[str, str], AlignmentGroup] = {}

    for entity in entities:
        key = entity.align_key()
        if not key:
            entity.aligned = False
            report.unaligned.append(entity)
            continue
        bucket_key = (entity.entity_type, key)
        group = buckets.get(bucket_key)
        if group is None:
            group = AlignmentGroup(entity_type=entity.entity_type, align_key=key)
            buckets[bucket_key] = group
            report.groups.append(group)
        group.entities.append(entity)

    for group in report.groups:
        # A group with a single system is a valid (non-cross-system) group.
        for entity in group.entities:
            entity.aligned = True

    return report


def missing_systems(
    group: AlignmentGroup,
    *,
    expected_systems: Iterable[str],
) -> list[str]:
    """Which expected systems have no entity in an aligned group (gap report)."""
    present = set(group.systems)
    return sorted(system for system in expected_systems if system not in present)


def join_cross_system(
    report: AlignmentReport,
    *,
    expected_systems: Iterable[str],
) -> list[dict[str, object]]:
    """Join aligned groups across systems, labelling each result (FR-5).

    A group missing some expected systems is still returned, with the missing
    systems listed — the query is not refused (FR-6).
    """
    expected = list(expected_systems)
    joined: list[dict[str, object]] = []
    for group in report.groups:
        joined.append(
            {
                "entityType": group.entity_type,
                "alignKey": group.align_key,
                "systems": group.systems,
                "recordIds": [entity.record_id for entity in group.entities],
                "missingSystems": missing_systems(group, expected_systems=expected),
                "crossSystem": group.is_cross_system,
            }
        )
    return joined
