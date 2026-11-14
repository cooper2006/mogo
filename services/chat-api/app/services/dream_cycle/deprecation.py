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

from app.services.dream_cycle.evolution_audit import EvolutionConfig

#: 011 T014 low-adoption thresholds (shared with 016). These mirror the single
#: source of truth in ``EvolutionConfig`` so the two cannot drift apart (T018).
#: They are kept as module-level names (not literals) so downstream code such
#: as ``SkillAdoption`` defaults and ``detect_low_adoption`` stay in sync.
_LOW_ADOPTION_CONFIG = EvolutionConfig()
LOW_ADOPTION_WINDOW_DAYS = _LOW_ADOPTION_CONFIG.low_adoption_window_days
LOW_ADOPTION_MIN_EXPOSURE = _LOW_ADOPTION_CONFIG.low_adoption_min_exposure
LOW_ADOPTION_THRESHOLD = _LOW_ADOPTION_CONFIG.low_adoption_rate
# 016 shared deprecation flag (the *aggregated* bit both 011 and 016 may set).
LOW_QUALITY_FLAG = "marked_low_quality"
# 011's own source bit. The aggregated ``marked_low_quality`` is the OR of the two
# independent source bits (011 adoption / 016 quality) so either side can flag a
# skill for down-ranking without the other side's restore wiping its mark.
SOURCE_011_ADOPTION = "flagged_by_011_adoption"
SOURCE_016_QUALITY = "flagged_by_016_quality"
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
) -> dict[str, Any]:
    """011 T014: mark the skill deprecated (shares 016 ``marked_low_quality``).

    The actual bit is persisted by ``AdoptionStore.mark_deprecated`` so the 016
    market side can read it back; this function only builds the audit record.
    """
    record: dict[str, Any] = {
        "skill_key": skill.skill_key,
        "tenant_id": skill.tenant_id,
        LOW_QUALITY_FLAG: True,
        "deprecated": True,
        "reason": "low_adoption",
        "effective_scope": TENANT_SCOPE,
    }
    skill.is_deprecated = True
    return record


class AdoptionStore:
    """Low-adoption counter + deprecation store (011 T015 / T014).

    T002-1 / ET005 / SEC001 / T009-3: the store is **tenant-partitioned**. The
    durable backend is a MongoDB collection (``skill_adoption``) keyed by
    ``(tenant_id, skill_key)`` with a unique compound index, so one tenant's
    adoption counters can never bleed into another's. When no DB is bound (unit
    tests, pure-library use) it falls back to an in-process dict with the same
    key shape, so behaviour stays exercisable without Mongo.
    """

    COLLECTION = "skill_adoption"

    def __init__(self, *, db: Any | None = None) -> None:
        self._db = db
        # In-memory fallback keyed by (tenant_id, skill_key).
        self._mem: dict[tuple[str, str], dict[str, Any]] = {}

    # -- backend helpers --------------------------------------------------------

    @property
    def _uses_db(self) -> bool:
        return self._db is not None

    @staticmethod
    def _doc_key(tenant_id: str, skill_key: str) -> dict[str, Any]:
        return {"tenant_id": tenant_id, "skill_key": skill_key}

    async def ensure_indexes(self) -> None:
        """Create the tenant-partitioned unique index (idempotent)."""
        if not self._uses_db:
            return
        await self._db[self.COLLECTION].create_index(
            [("tenant_id", 1), ("skill_key", 1)],
            unique=True,
            name="skill_adoption_tenant_skill",
        )

    # -- writes -----------------------------------------------------------------

    def record_exposure(self, skill_key: str, tenant_id: str) -> None:
        if self._uses_db:
            self._db[self.COLLECTION].update_one(
                self._doc_key(tenant_id, skill_key),
                {
                    "$inc": {"exposure": 1},
                    "$setOnInsert": {
                        "adopted": 0,
                        "is_deprecated": False,
                        LOW_QUALITY_FLAG: False,
                        SOURCE_011_ADOPTION: False,
                        SOURCE_016_QUALITY: False,
                    },
                },
                upsert=True,
            )
            return
        counter = self._mem.setdefault(
            (tenant_id, skill_key),
            {
                "exposure": 0,
                "adopted": 0,
                "is_deprecated": False,
                LOW_QUALITY_FLAG: False,
                SOURCE_011_ADOPTION: False,
                SOURCE_016_QUALITY: False,
            },
        )
        counter["exposure"] += 1

    def record_adoption(self, skill_key: str, tenant_id: str) -> None:
        if self._uses_db:
            self._db[self.COLLECTION].update_one(
                self._doc_key(tenant_id, skill_key),
                {
                    "$inc": {"exposure": 1, "adopted": 1},
                    "$setOnInsert": {
                        "is_deprecated": False,
                        LOW_QUALITY_FLAG: False,
                        SOURCE_011_ADOPTION: False,
                        SOURCE_016_QUALITY: False,
                    },
                },
                upsert=True,
            )
            return
        counter = self._mem.setdefault(
            (tenant_id, skill_key),
            {
                "exposure": 0,
                "adopted": 0,
                "is_deprecated": False,
                LOW_QUALITY_FLAG: False,
                SOURCE_011_ADOPTION: False,
                SOURCE_016_QUALITY: False,
            },
        )
        counter["exposure"] += 1
        counter["adopted"] += 1

    def mark_deprecated(self, skill_key: str, tenant_id: str, record: dict[str, Any]) -> None:
        """011 T014: persist the shared ``marked_low_quality`` bit (consumed by 016).

        Only the 011 source bit is set; the aggregated ``marked_low_quality`` is
        the OR of the two source bits (011 adoption / 016 quality), so 016's own
        quality mark survives this write.
        """
        if self._uses_db:
            self._db[self.COLLECTION].update_one(
                self._doc_key(tenant_id, skill_key),
                {"$set": {SOURCE_011_ADOPTION: True, LOW_QUALITY_FLAG: True, "is_deprecated": True}},
                upsert=True,
            )
        else:
            counter = self._mem.setdefault(
                (tenant_id, skill_key),
                {
                    "exposure": 0,
                    "adopted": 0,
                    "is_deprecated": False,
                    LOW_QUALITY_FLAG: False,
                    SOURCE_011_ADOPTION: False,
                    SOURCE_016_QUALITY: False,
                },
            )
            counter["is_deprecated"] = True
            counter[SOURCE_011_ADOPTION] = True
            counter[LOW_QUALITY_FLAG] = True
        record["marked_low_quality"] = True

    def restore(self, skill_key: str, tenant_id: str) -> dict[str, Any]:
        """011 T015: manual restore — reset adoption counter + re-enable recommendation.

        Only the 011 source bit is cleared. The aggregated ``marked_low_quality``
        is recomputed: it stays True if the 016 quality bit is still set, so a
        016-side mark is never wiped by an 011-side restore (T014-3 / T015-2).
        """
        if self._uses_db:
            # Pipeline update lets us derive marked_low_quality from the surviving
            # 016 source bit instead of blindly clearing it.
            self._db[self.COLLECTION].update_one(
                self._doc_key(tenant_id, skill_key),
                [
                    {
                        "$set": {
                            "exposure": 0,
                            "adopted": 0,
                            "is_deprecated": False,
                            SOURCE_011_ADOPTION: False,
                            LOW_QUALITY_FLAG: {"$or": [f"${SOURCE_016_QUALITY}", False]},
                        }
                    }
                ],
                upsert=True,
            )
            doc = self._db[self.COLLECTION].find_one(self._doc_key(tenant_id, skill_key))
            aggregated = bool(doc.get(LOW_QUALITY_FLAG)) if doc else False
        else:
            counter = self._mem.setdefault(
                (tenant_id, skill_key),
                {
                    "exposure": 0,
                    "adopted": 0,
                    "is_deprecated": False,
                    LOW_QUALITY_FLAG: False,
                    SOURCE_011_ADOPTION: False,
                    SOURCE_016_QUALITY: False,
                },
            )
            counter["exposure"] = 0
            counter["adopted"] = 0
            counter["is_deprecated"] = False
            counter[SOURCE_011_ADOPTION] = False
            counter[LOW_QUALITY_FLAG] = bool(counter[SOURCE_016_QUALITY])
            aggregated = counter[LOW_QUALITY_FLAG]
        return {
            "skill_key": skill_key,
            "tenant_id": tenant_id,
            "restored": True,
            LOW_QUALITY_FLAG: aggregated,
            "recommendation": "re-enabled",
        }

    # -- reads ------------------------------------------------------------------

    def get(self, skill_key: str, tenant_id: str) -> SkillAdoption:
        if self._uses_db:
            doc = self._db[self.COLLECTION].find_one(self._doc_key(tenant_id, skill_key))
        else:
            doc = self._mem.get((tenant_id, skill_key))
        if doc is None:
            return SkillAdoption(skill_key=skill_key, tenant_id=tenant_id)
        return SkillAdoption(
            skill_key=skill_key,
            tenant_id=str(doc.get("tenant_id") or tenant_id),
            exposure=int(doc.get("exposure") or 0),
            adopted=int(doc.get("adopted") or 0),
            window_days=int(doc.get("window_days") or LOW_ADOPTION_WINDOW_DAYS),
            is_deprecated=bool(doc.get(LOW_QUALITY_FLAG)),
        )


def deprecation_flow(
    skill_key: str,
    tenant_id: str,
    store: AdoptionStore,
) -> dict[str, Any]:
    """Run the US4 low-adoption flow on a stored skill, returning the outcome."""
    skill = store.get(skill_key, tenant_id)
    if detect_low_adoption(skill):
        record = mark_deprecated(skill)
        store.mark_deprecated(skill_key, tenant_id, record)
        record["action"] = "deprecated"
        record["tenant_id"] = tenant_id
        return record
    record = {
        "skill_key": skill_key,
        "tenant_id": tenant_id,
        LOW_QUALITY_FLAG: False,
        "action": "kept",
    }
    return record
