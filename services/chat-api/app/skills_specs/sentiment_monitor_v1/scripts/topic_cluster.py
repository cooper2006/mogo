"""Lightweight topic clustering for sentiment monitoring (no ML dependency)."""

from __future__ import annotations

import re
from typing import Iterable, Mapping

_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}")

_THEME_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "账号体系": ("账号", "登录", "切换", "account", "login"),
    "价格与计费": ("价格", "收费", "涨价", "计费", "price", "pricing", "billing"),
    "性能与稳定性": ("卡", "慢", "崩溃", "掉线", "slow", "crash", "latency"),
    "功能缺失": ("缺少", "没有", "不支持", "missing", "unsupported"),
    "迁移成本": ("迁移", "导出", "兼容", "migration", "export"),
}


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(str(text or ""))


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def classify_theme(text: str) -> str:
    """Assign one theme label, defaulting to 其他."""
    lowered = str(text or "").lower()
    best, best_hits = "其他", 0
    for theme, keywords in _THEME_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword.lower() in lowered)
        if hits > best_hits:
            best, best_hits = theme, hits
    return best


def cluster_topics(texts: Iterable[str]) -> dict[str, int]:
    """Count how many texts fall into each theme."""
    counts: dict[str, int] = {}
    for text in texts:
        theme = classify_theme(text)
        counts[theme] = counts.get(theme, 0) + 1
    return counts


def sentiment_distribution(scores: Iterable[float]) -> dict[str, float]:
    """Bucket scores in [-1, 1] into positive / neutral / negative shares."""
    values = [float(s) for s in scores]
    total = len(values)
    if total == 0:
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    positive = sum(1 for v in values if v > 0.1) / total
    negative = sum(1 for v in values if v < -0.1) / total
    return {"positive": positive, "neutral": 1.0 - positive - negative, "negative": negative}
