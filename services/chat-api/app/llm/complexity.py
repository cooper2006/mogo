"""040-model-tier-routing: 任务复杂度评估（纯函数，无 IO）。

定位：按可计算特征把一次 LLM 请求落入 ``light`` / ``mid`` / ``high`` 三档之一。
**不读配置、不发请求**——阈值由调用方（``ModelRouter``）从 ``model_routing.yaml``
的 ``tiering.thresholds`` 读入后作为可变部分传入，本模块只提供缺省常量与判定规则，
保证可单测、无隐藏依赖（spec FR-003 / 决策 2）。

判定口径见 ``specs/040-model-tier-routing/spec.md`` 的 R-4/R-6/R-15/R-16：

* 每命中一项"高复杂度特征"记 1 分：``score >= 2`` → ``high``，``score == 1`` →
  ``mid``，``score == 0`` → ``light``；
* ``declared_complexity``（调用方显式声明）优先于评分；
* 调用方**完全未提供**上下文特征（``features_supplied=False``）→ ``mid``；
* 评估过程异常 → ``mid`` 并带上 ``error`` 供调用方告警。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple


ModelTier = str

TIER_LIGHT = "light"
TIER_MID = "mid"
TIER_HIGH = "high"

VALID_TIERS: Tuple[str, ...] = (TIER_LIGHT, TIER_MID, TIER_HIGH)
DEFAULT_TIER: ModelTier = TIER_MID

#: 评分权重（R-4）：每个高复杂度特征计 1 分。
TIER_SCORE_HIGH = 2
TIER_SCORE_MID = 1

#: 缺省阈值（yaml ``tiering.thresholds`` 逐键浅合并覆盖，不整体替换）。
DEFAULT_TIERING_THRESHOLDS: Dict[str, Any] = {
    "prompt_chars_high": 4000,
    "tool_count_high": 8,
    "multi_turn_high": 4,
    "high_stages": ("coding",),
    "high_intents": ("coding",),
}


@dataclass(frozen=True)
class TaskComplexityFeatures:
    """一次请求的可计算复杂度特征（R-1）。

    ``None`` 表示调用方**未提供**该特征（区别于"提供了但值为 0"）；三个数值特征
    全为 ``None`` 时 ``features_supplied`` 为 ``False``（R-6 的缺省路径）。
    """

    prompt_chars: int | None = None
    tool_count: int | None = None
    multi_turn: int | None = None
    stage: str = ""
    intent: str = ""
    declared_complexity: str = ""

    @property
    def features_supplied(self) -> bool:
        return any(
            value is not None
            for value in (self.prompt_chars, self.tool_count, self.multi_turn)
        )


@dataclass(frozen=True)
class TierDecision:
    """评估结论：档位 + 命中依据 + 异常（供调用方告警，R-5 的 ``evaluator_error``）。"""

    tier: ModelTier
    score: int = 0
    hits: Tuple[str, ...] = field(default_factory=tuple)
    declared: str = ""
    error: str = ""


def merge_thresholds(overrides: Mapping[str, Any] | None) -> Dict[str, Any]:
    """逐键浅合并阈值覆盖（缺键沿用缺省常量，非法值丢弃）。"""

    merged = dict(DEFAULT_TIERING_THRESHOLDS)
    if not isinstance(overrides, Mapping):
        return merged
    for key, value in overrides.items():
        if key not in merged:
            continue
        if key in ("high_stages", "high_intents"):
            if isinstance(value, (list, tuple)):
                merged[key] = tuple(str(item) for item in value if str(item or "").strip())
            continue
        try:
            merged[key] = int(value)
        except (TypeError, ValueError):
            continue
    return merged


def normalize_declared(value: Any) -> str:
    """合法声明值归一；非法（非三档 / 大小写混杂 / 含空白）返回空串（R-7）。"""

    raw = str(value or "")
    if raw != raw.strip():
        return ""
    normalized = raw.lower()
    return normalized if normalized in VALID_TIERS else ""


def _score(features: TaskComplexityFeatures, thresholds: Dict[str, Any]) -> TierDecision:
    hits: list[str] = []

    prompt_chars = int(features.prompt_chars or 0)
    if prompt_chars >= int(thresholds["prompt_chars_high"]):
        hits.append("prompt_chars")

    tool_count = int(features.tool_count or 0)
    if tool_count >= int(thresholds["tool_count_high"]):
        hits.append("tool_count")

    multi_turn = int(features.multi_turn or 0)
    if multi_turn >= int(thresholds["multi_turn_high"]):
        hits.append("multi_turn")

    stage = str(features.stage or "").strip().lower()
    if stage and stage in tuple(thresholds["high_stages"]):
        hits.append("stage")

    intent = str(features.intent or "").strip().lower()
    if intent and intent in tuple(thresholds["high_intents"]):
        hits.append("intent")

    score = len(hits)
    if score >= TIER_SCORE_HIGH:
        tier = TIER_HIGH
    elif score == TIER_SCORE_MID:
        tier = TIER_MID
    else:
        tier = TIER_LIGHT
    return TierDecision(tier=tier, score=score, hits=tuple(hits))


def evaluate_tier(
    features: TaskComplexityFeatures,
    thresholds: Mapping[str, Any] | None = None,
) -> TierDecision:
    """评估档位（R-7 的 ④ 显式声明 → ⑤ 规则评分 → ⑥ 缺省/异常落 ``mid``）。"""

    try:
        if not isinstance(features, TaskComplexityFeatures):
            return TierDecision(tier=DEFAULT_TIER, error="features_invalid")

        declared = normalize_declared(features.declared_complexity)
        if declared:
            return TierDecision(tier=declared, score=0, hits=(), declared=declared)

        if not features.features_supplied:
            return TierDecision(tier=DEFAULT_TIER, score=0, hits=(), error="features_absent")

        return _score(features, merge_thresholds(thresholds))
    except Exception as exc:  # pragma: no cover - defensive; 纯函数不应抛错
        return TierDecision(tier=DEFAULT_TIER, error=f"{type(exc).__name__}: {exc}")
