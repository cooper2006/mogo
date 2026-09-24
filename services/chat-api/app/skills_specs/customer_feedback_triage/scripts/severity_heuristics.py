"""Severity heuristics for the ``customer_feedback_triage`` Skill.

The rules here are deliberately deterministic and dependency-free so that the
triage pipeline and its acceptance tests can run without an LLM or network
access. An LLM may still refine the classification upstream; these heuristics
define the floor that the case's acceptance criteria are measured against
(P0 recall >= 95% on the labelled sample in the acceptance tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

_UTC8 = timezone(timedelta(hours=8))

P0 = "P0"
P1 = "P1"
P2 = "P2"
P3 = "P3"

SEVERITY_ORDER: tuple[str, ...] = (P0, P1, P2, P3)


# Keyword sets. Chinese terms come from the case document; the English terms let
# the same rules serve mixed-language batches.
DEFAULT_P0_KEYWORDS: tuple[str, ...] = (
    "无法登录",
    "登录不了",
    "数据丢失",
    "数据没了",
    "服务不可用",
    "服务挂了",
    "支付失败",
    "扣款失败",
    "系统崩溃",
    "崩溃",
    "宕机",
    "不可用",
    "cannot login",
    "can't login",
    "data loss",
    "service unavailable",
    "payment failed",
    "outage",
    "crash",
)

DEFAULT_P1_KEYWORDS: tuple[str, ...] = (
    "功能异常",
    "报错",
    "异常",
    "性能问题",
    "很慢",
    "超时",
    "卡顿",
    "失败",
    "无法提交",
    "无法保存",
    "error",
    "slow",
    "timeout",
    "broken",
    "fail",
)

DEFAULT_P2_KEYWORDS: tuple[str, ...] = (
    "功能请求",
    "希望支持",
    "建议增加",
    "体验问题",
    "不好用",
    "不方便",
    "feature request",
    "would be nice",
    "usability",
    "confusing",
)

DEFAULT_P3_KEYWORDS: tuple[str, ...] = (
    "建议",
    "表扬",
    "感谢",
    "不错",
    "很好用",
    "thanks",
    "praise",
    "great",
)

# Categories aligned with the case document's default taxonomy.
DEFAULT_TAXONOMY: tuple[str, ...] = (
    "登录账号",
    "数据同步",
    "性能",
    "计费",
    "集成",
    "内容",
    "权限",
    "其他",
)

CATEGORY_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "登录账号": ("登录", "账号", "密码", "验证码", "login", "account", "password", "sso"),
    "数据同步": ("同步", "数据丢失", "丢失", "不一致", "sync", "data loss", "inconsistent"),
    "性能": ("性能", "慢", "超时", "卡顿", "响应", "slow", "timeout", "latency", "performance"),
    "计费": ("计费", "支付", "扣款", "账单", "发票", "价格", "billing", "payment", "invoice", "price"),
    "集成": ("集成", "接口", "API", "对接", "webhook", "integration", "connector"),
    "内容": ("内容", "文本", "格式", "排版", "导出", "content", "format", "export"),
    "权限": ("权限", "角色", "可见", "越权", "permission", "role", "access"),
}

# Sentiment lexicon: negative terms push severity up, positive terms down.
NEGATIVE_TERMS: tuple[str, ...] = (
    "急",
    "紧急",
    "严重",
    "崩溃",
    "投诉",
    "愤怒",
    "太差",
    "无法",
    "不能",
    "urgent",
    "critical",
    "angry",
    "terrible",
    "unacceptable",
    "blocker",
)

POSITIVE_TERMS: tuple[str, ...] = (
    "感谢",
    "赞",
    "不错",
    "满意",
    "好评",
    "thanks",
    "great",
    "love",
    "excellent",
)


@dataclass(frozen=True)
class SeverityAssessment:
    severity: str
    score: float
    reasons: tuple[str, ...] = ()
    category: str = "其他"


@dataclass
class HeuristicConfig:
    """Keyword/sentiment configuration, overridable by tenant context."""

    p0_keywords: tuple[str, ...] = DEFAULT_P0_KEYWORDS
    p1_keywords: tuple[str, ...] = DEFAULT_P1_KEYWORDS
    p2_keywords: tuple[str, ...] = DEFAULT_P2_KEYWORDS
    p3_keywords: tuple[str, ...] = DEFAULT_P3_KEYWORDS
    negative_terms: tuple[str, ...] = NEGATIVE_TERMS
    positive_terms: tuple[str, ...] = POSITIVE_TERMS
    taxonomy: tuple[str, ...] = DEFAULT_TAXONOMY
    category_keywords: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: CATEGORY_KEYWORDS
    )

    @classmethod
    def from_tenant_context(cls, tenant_context: Mapping[str, Any] | None) -> "HeuristicConfig":
        """Build a config from ``tenant_context`` (see the case input contract)."""
        if not tenant_context:
            return cls()
        context = dict(tenant_context)
        p0_extra = _as_tuple(context.get("p0_keywords"))
        taxonomy = _as_tuple(context.get("modules")) or DEFAULT_TAXONOMY
        return cls(
            p0_keywords=DEFAULT_P0_KEYWORDS + p0_extra,
            taxonomy=taxonomy,
        )


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def _matches(text: str, terms: Sequence[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term and term.lower() in lowered]


def sentiment_score(text: str, config: HeuristicConfig) -> float:
    """Return a sentiment score in ``[-1, 1]``; negative means unhappy user."""
    negative = len(_matches(text, config.negative_terms))
    positive = len(_matches(text, config.positive_terms))
    total = negative + positive
    if total == 0:
        return 0.0
    return (positive - negative) / total


def classify_category(text: str, config: HeuristicConfig) -> str:
    """Assign a module-level category, defaulting to ``其他``."""
    scores: dict[str, int] = {}
    for category, keywords in config.category_keywords.items():
        if category not in config.taxonomy:
            continue
        hits = len(_matches(text, keywords))
        if hits:
            scores[category] = hits
    if not scores:
        return "其他" if "其他" in config.taxonomy else config.taxonomy[-1]
    # Stable: highest hit count, then taxonomy order for deterministic ties.
    best = max(scores.items(), key=lambda item: (item[1], -config.taxonomy.index(item[0])))
    return best[0]


def classify_severity(
    text: str,
    *,
    config: HeuristicConfig | None = None,
    timestamp: str | None = None,
    affected_users: int = 1,
) -> SeverityAssessment:
    """Classify one feedback item into P0–P3 with an auditable reason list.

    P0 requires a high-impact keyword AND a not-positive sentiment, matching the
    case document ("关键词 + 情感极负面"). Everything else falls back through
    P1 and P2 to P3.
    """
    cfg = config or HeuristicConfig()
    body = str(text or "")
    reasons: list[str] = []

    p0_hits = _matches(body, cfg.p0_keywords)
    p1_hits = _matches(body, cfg.p1_keywords)
    p2_hits = _matches(body, cfg.p2_keywords)
    p3_hits = _matches(body, cfg.p3_keywords)
    sentiment = sentiment_score(body, cfg)

    impacted = max(1, int(affected_users or 1))

    if p0_hits and sentiment <= 0:
        reasons.append(f"p0_keywords={p0_hits}")
        if sentiment < 0:
            reasons.append(f"negative_sentiment={sentiment:.2f}")
        if impacted > 1:
            reasons.append(f"affected_users={impacted}")
        score = 100.0 + len(p0_hits) * 5 + impacted
        return SeverityAssessment(P0, score, tuple(reasons), classify_category(body, cfg))

    if p0_hits:
        # High-impact keyword but the user is happy (e.g. "解决了无法登录的问题，感谢")
        reasons.append("p0_keyword_with_positive_sentiment")
        return SeverityAssessment(P2, 40.0, tuple(reasons), classify_category(body, cfg))

    if p1_hits:
        reasons.append(f"p1_keywords={p1_hits}")
        score = 70.0 + len(p1_hits) * 3
        return SeverityAssessment(P1, score, tuple(reasons), classify_category(body, cfg))

    if p2_hits:
        reasons.append(f"p2_keywords={p2_hits}")
        return SeverityAssessment(P2, 40.0 + len(p2_hits) * 2, tuple(reasons), classify_category(body, cfg))

    if p3_hits or sentiment > 0:
        reasons.append("non_blocking_feedback")
        return SeverityAssessment(P3, 10.0, tuple(reasons), classify_category(body, cfg))

    reasons.append("no_keyword_match_default_p2")
    return SeverityAssessment(P2, 35.0, tuple(reasons), classify_category(body, cfg))


def rank_score(
    *,
    severity: str,
    timestamp: str | None,
    affected_users: int = 1,
    sentiment: float = 0.0,
    now_epoch: float | None = None,
) -> float:
    """Score P0/P1 items for action ranking (urgency × impact × sentiment).

    Higher is more urgent. ``timestamp`` is an ISO-8601 string; unparseable or
    missing timestamps fall back to a neutral recency contribution instead of
    raising, because one malformed row must not sink the whole batch.
    """
    severity_weight = {P0: 1000.0, P1: 300.0, P2: 50.0, P3: 10.0}.get(severity, 10.0)

    recency = 0.0
    parsed = _parse_epoch(timestamp)
    if parsed is not None:
        reference = now_epoch if now_epoch is not None else _now_epoch()
        age_hours = max(0.0, (reference - parsed) / 3600.0)
        # Fresher items rank higher; decay over a 7-day window.
        recency = max(0.0, 168.0 - age_hours)

    impact = min(max(int(affected_users or 1), 1), 1000) * 2.0
    negativity = max(0.0, -float(sentiment or 0.0)) * 100.0

    return severity_weight + recency + impact + negativity


def _parse_epoch(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    value = str(timestamp).strip().replace("Z", "+00:00")
    for parser in (
        lambda item: datetime.fromisoformat(item),
        lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
        lambda item: datetime.strptime(item, "%Y/%m/%d %H:%M"),
        lambda item: datetime.strptime(item, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(value)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_UTC8)
        return parsed.timestamp()
    return None


def _now_epoch() -> float:
    """Current time as an epoch in the batch's reference timezone (UTC+8)."""
    return datetime.now(tz=_UTC8).timestamp()

