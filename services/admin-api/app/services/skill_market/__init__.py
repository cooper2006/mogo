"""Skill market hardening (feature 016).

Layers market-side monitoring, effect scoring, canary rollout / rollback, and
low-quality marking **on top of** 004's Skill version model — 004's draft/publish
contract is unchanged.

This package holds the dependency-light core (effect score / canary / thresholds),
so it is unit-testable without a database.
"""

from __future__ import annotations

from .scoring import (
    DEFAULT_EFFECT_THRESHOLDS,
    EFFECT_WEIGHTS,
    LOW_QUALITY_MARKER,
    EffectScore,
    compute_effect_score,
    inspect_skill_quality,
    is_low_quality,
    mark_low_quality,
    restore_skill_quality,
)
from .adoption_client import (
    apply_quality_assessment,
    restore_quality,
)
from .quality_metrics import (
    DEFAULT_INTERVAL_SECONDS,
    MIN_EFFECT_SAMPLES,
    PROJECTIONS_COLLECTION,
    QUALITY_METRICS_COLLECTION,
    SkillQualityScanner,
    collect_skill_activity_metrics,
    evaluate_all,
    evaluate_skill_quality,
    record_skill_call,
)
from .canary import (
    DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    DEFAULT_MIN_CANARY_SAMPLES,
    CanaryDecision,
    RolloutState,
    evaluate_canary,
)

__all__ = [
    "EffectScore",
    "compute_effect_score",
    "is_low_quality",
    "mark_low_quality",
    "restore_skill_quality",
    "inspect_skill_quality",
    "apply_quality_assessment",
    "restore_quality",
    "record_skill_call",
    "collect_skill_activity_metrics",
    "evaluate_skill_quality",
    "evaluate_all",
    "SkillQualityScanner",
    "QUALITY_METRICS_COLLECTION",
    "PROJECTIONS_COLLECTION",
    "MIN_EFFECT_SAMPLES",
    "DEFAULT_INTERVAL_SECONDS",
    "LOW_QUALITY_MARKER",
    "EFFECT_WEIGHTS",
    "DEFAULT_EFFECT_THRESHOLDS",
    "RolloutState",
    "CanaryDecision",
    "evaluate_canary",
    "DEFAULT_CANARY_ROLLBACK_THRESHOLD",
    "DEFAULT_MIN_CANARY_SAMPLES",
]
