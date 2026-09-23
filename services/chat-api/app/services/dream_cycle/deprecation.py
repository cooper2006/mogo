"""Low-adoption detection + deprecation (011 T014-T015 / US4).

Detects low adoption (exposure ≥ 20 over a 14-day window with adoption < 10%)
and marks the skill as *deprecated*. The deprecation flag is shared with the
016 hardening's ``marked_low_quality`` bit, and deprecation takes effect
within the tenant. A manual restore resets the adoption counter and re-enables
recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# 011 T014 low-adoption thresholds (shared with 016).
LOW_ADOPTION_WINDOW_DAYS = 14
LOW_ADOPTION_MIN_EXPOSURE = 20
LOW_ADOPTION_THRESHOLD = 0.10
# 016 shared deprecation flag.
LOW_QUALITY_FLAG = "marked_low_quality"
TENANT_SCOPE = "tenant"


@dataclass
class SkillAdoption:
    skill_key: str
    tenant_id: str
    exposure: int = 0
    adopted: int = 0
    window_days: int = LOW_ADOPTION_WINDOW_DAYS
    is_deprecated: bool = False

    @property
    def adoption_rate(self) -> Optional[float]:
        if self.exposure <= 0:
            return None
        return self.adopted / self.exposure


def detect_low_adoption(skill: SkillAdoption) -> bool:
    """011 T014: low adoption = exposure ≥ 20, window ≤ 14d, adoption < 10%."""
    rate = skill.adoption_rate
    if rate is None:
        return False
    return (
        skill.exposure >= LOW_ADOPTION_MIN_EXPOSURE
        and skill.window_days <= LOW_ADOPTION_WINDOW_DAYS
        and rate < LOW_ADOPTION_THRESHOLD
    )


def mark_deprecated(
    skill: SkillAdoption,
    *,
    flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """011 T014: mark the skill deprecated (shares 016 ``marked_low_quality``)."""
    record: dict[str, Any] = {
        "skill_key": skill.skill_key,
        "tenant_id": skill.tenant_id,
        LOW_QUALITY_FLAG: True,
        "deprecated": True,
        "reason": "low_adoption",
        "effective_scope": TENANT_SCOPE,
    }
    if flags is not None:
        flags[LOW_QUALITY_FLAG] = True
    skill.is_deprecated = True
    return record


class AdoptionStore:
    """In-memory adoption counter + deprecation store (011 T015)."""

    def __init__(self) -> None:
        self.counters: dict[str, dict[str, int]] = {}
        self.flags: dict[str, dict[str, bool]] = {}

    def record_exposure(self, skill_key: str, tenant_id: str) -> None:
        counter = self.counters.setdefault(
            skill_key, {"exposure": 0, "adopted": 0, "tenant_id": tenant_id}
        )
        counter["exposure"] += 1

    def record_adoption(self, skill_key: str, tenant_id: str) -> None:
        counter = self.counters.setdefault(
            skill_key, {"exposure": 0, "adopted": 0, "tenant_id": tenant_id}
        )
        counter["exposure"] += 1
        counter["adopted"] += 1

    def get(self, skill_key: str) -> SkillAdoption:
        counter = self.counters.get(skill_key, {"exposure": 0, "adopted": 0, "tenant_id": ""})
        return SkillAdoption(
            skill_key=skill_key,
            tenant_id=str(counter.get("tenant_id") or ""),
            exposure=int(counter.get("exposure") or 0),
            adopted=int(counter.get("adopted") or 0),
            is_deprecated=bool(self.flags.get(skill_key, {}).get(LOW_QUALITY_FLAG)),
        )

    def mark_deprecated(self, skill_key: str, record: dict[str, Any]) -> None:
        flags = self.flags.setdefault(skill_key, {})
        flags[LOW_QUALITY_FLAG] = True
        record["marked_low_quality"] = True

    def restore(self, skill_key: str) -> dict[str, Any]:
        """011 T015: manual restore — reset adoption counter + re-enable recommendation."""
        counter = self.counters.get(skill_key)
        if counter is not None:
            counter["exposure"] = 0
            counter["adopted"] = 0
        flags = self.flags.setdefault(skill_key, {})
        flags[LOW_QUALITY_FLAG] = False
        return {
            "skill_key": skill_key,
            "restored": True,
            LOW_QUALITY_FLAG: False,
            "recommendation": "re-enabled",
        }


def deprecation_flow(
    skill_key: str,
    tenant_id: str,
    store: AdoptionStore,
) -> dict[str, Any]:
    """Run the US4 low-adoption flow on a stored skill, returning the outcome."""
    skill = store.get(skill_key)
    if detect_low_adoption(skill):
        record = mark_deprecated(skill, flags=store.flags.setdefault(skill_key, {}))
        store.mark_deprecated(skill_key, record)
        record["action"] = "deprecated"
        return record
    record = {
        "skill_key": skill_key,
        "tenant_id": tenant_id,
        LOW_QUALITY_FLAG: False,
        "action": "kept",
    }
    return record
