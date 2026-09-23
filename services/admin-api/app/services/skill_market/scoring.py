"""Skill effect scoring + low-quality marking (016 FR-3 / FR-6 / clarify OQ-1 / OQ-4).

Effect score is a weighted blend:

* success rate        0.5
* adoption rate       0.3
* correction (inverse) 0.2   (fewer corrections -> higher score)

Weights are configurable. A Skill is marked **low quality** when its effect score
stays below 0.4 for 7 consecutive days (clarify OQ-4); the marker shares the
``skill_status.marked_low_quality`` flag with 011 (avoid double-writing).
"""

from __future__ import annotations

from dataclasses import dataclass

# Effect-score weights (clarify OQ-1).
EFFECT_WEIGHTS: dict[str, float] = {
    "success": 0.5,
    "adoption": 0.3,
    "correction_inverse": 0.2,
}

# Low-quality threshold + the sustained window (clarify OQ-4).
LOW_QUALITY_THRESHOLD = 0.4
LOW_QUALITY_SUSTAINED_DAYS = 7

DEFAULT_EFFECT_THRESHOLDS: dict[str, float] = {
    "low_quality": LOW_QUALITY_THRESHOLD,
    "sustained_days": float(LOW_QUALITY_SUSTAINED_DAYS),
}

# The shared marker key used by both 011 and 016.
LOW_QUALITY_MARKER = "marked_low_quality"


@dataclass
class EffectScore:
    """A computed effect score plus its component rates."""

    score: float
    success_rate: float = 0.0
    adoption_rate: float = 0.0
    correction_rate: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "score": round(self.score, 4),
            "successRate": round(self.success_rate, 4),
            "adoptionRate": round(self.adoption_rate, 4),
            "correctionRate": round(self.correction_rate, 4),
        }


def compute_effect_score(
    *,
    total_calls: int,
    successful_calls: int,
    adopted_calls: int,
    corrected_calls: int,
    weights: dict[str, float] | None = None,
) -> EffectScore:
    """Compute the weighted effect score.

    Rates are computed over ``total_calls``; an empty sample yields a zero score
    (never a division error).
    """
    resolved = weights or EFFECT_WEIGHTS
    total = max(0, int(total_calls))
    if total == 0:
        return EffectScore(score=0.0)

    success_rate = max(0.0, min(1.0, int(successful_calls) / total))
    adoption_rate = max(0.0, min(1.0, int(adopted_calls) / total))
    correction_rate = max(0.0, min(1.0, int(corrected_calls) / total))
    correction_inverse = 1.0 - correction_rate

    score = (
        success_rate * resolved.get("success", 0.0)
        + adoption_rate * resolved.get("adoption", 0.0)
        + correction_inverse * resolved.get("correction_inverse", 0.0)
    )
    return EffectScore(
        score=score,
        success_rate=success_rate,
        adoption_rate=adoption_rate,
        correction_rate=correction_rate,
    )


def is_low_quality(
    *,
    score: float,
    sustained_days: int,
    threshold: float = LOW_QUALITY_THRESHOLD,
    required_days: int = LOW_QUALITY_SUSTAINED_DAYS,
) -> bool:
    """Whether a Skill should be marked low quality (below threshold, sustained)."""
    return float(score) < float(threshold) and int(sustained_days) >= int(required_days)
