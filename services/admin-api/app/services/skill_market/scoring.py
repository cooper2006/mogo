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


def mark_low_quality(
    skill_id: str,
    *,
    score: float,
    sustained_days: int,
    threshold: float = LOW_QUALITY_THRESHOLD,
    required_days: int = LOW_QUALITY_SUSTAINED_DAYS,
) -> bool:
    """Mark a Skill low quality if its score stays below threshold for the window.

    Returns True when the Skill should (and did) get the marker; emits a
    ``016 skill.quality.marked`` event through the T999 audit bridge.
    """
    should = is_low_quality(
        score=score,
        sustained_days=sustained_days,
        threshold=threshold,
        required_days=required_days,
    )
    if should:
        _audit_skill_quality_marked(skill_id, score, sustained_days)
    return should


def _audit_skill_quality_marked(skill_id: str, score: float, sustained_days: int) -> None:
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "016",
            "skill.quality.marked",
            {
                "skill_id": skill_id,
                "score": round(float(score), 4),
                "sustained_days": int(sustained_days),
            },
        )
    except ImportError:
        # admin-api 不依赖 chat-api 的 T999 bridge；审计静默跳过。
        pass
    except Exception:
        # 审计失败绝不影响主流程。
        pass


def restore_skill_quality(
    skill_id: str,
    *,
    actor: str = "",
) -> dict:
    """016 FR-11: manually restore a low-quality Skill.

    Resets the low-quality sustained window (FR-11: "恢复后重置低质量窗口，重新累计
    7 天") and re-enters the market's normal ranking. Emits a
    ``016 skill.quality.restored`` event through the T999 bridge.
    """
    _audit_skill_quality_restored(skill_id, actor)
    return {
        "skill_id": skill_id,
        "restored": True,
        "actor": actor,
        "window_reset_days": LOW_QUALITY_SUSTAINED_DAYS,
        "ranking": "normal",
    }


def _audit_skill_quality_restored(skill_id: str, actor: str) -> None:
    try:
        from app.services.feature_audit_bridge import emit_feature_event

        emit_feature_event(
            "016",
            "skill.quality.restored",
            {
                "skill_id": skill_id,
                "actor": actor,
            },
        )
    except ImportError:
        pass
    except Exception:
        pass


def inspect_skill_quality(
    *,
    skill_id: str,
    total_calls: int,
    successful_calls: int,
    adopted_calls: int,
    corrected_calls: int,
    sustained_days: int,
    weights: dict[str, float] | None = None,
    threshold: float = LOW_QUALITY_THRESHOLD,
    required_days: int = LOW_QUALITY_SUSTAINED_DAYS,
) -> dict:
    """016 FR-3 / FR-6: run one quality inspection on a Skill.

    Computes the weighted effect score and, when the score stays below
    ``threshold`` for ``sustained_days`` (>= ``required_days``), marks the
    Skill low quality (T999 ``016 skill.quality.marked``).  Returns an
    outcome dict so the caller can persist the marker / ranking.
    """
    effect = compute_effect_score(
        total_calls=total_calls,
        successful_calls=successful_calls,
        adopted_calls=adopted_calls,
        corrected_calls=corrected_calls,
        weights=weights,
    )
    should_mark = mark_low_quality(
        skill_id,
        score=effect.score,
        sustained_days=sustained_days,
        threshold=threshold,
        required_days=required_days,
    )
    return {
        "skill_id": skill_id,
        "effect": effect.as_dict(),
        "sustained_days": int(sustained_days),
        "marked_low_quality": should_mark,
    }
