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
    EffectScore,
    compute_effect_score,
    is_low_quality,
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
    "EFFECT_WEIGHTS",
    "DEFAULT_EFFECT_THRESHOLDS",
    "RolloutState",
    "CanaryDecision",
    "evaluate_canary",
    "DEFAULT_CANARY_ROLLBACK_THRESHOLD",
    "DEFAULT_MIN_CANARY_SAMPLES",
]
