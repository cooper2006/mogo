"""Localized research completion summaries."""

from __future__ import annotations


def research_summary(*, accepted_count: int, provider_searches: int, budget_exhausted: bool, language: str) -> str:
    if str(language or "").lower().startswith("zh"):
        suffix = " 已达到最大研究轮次，仍有未继续执行的候选查询。" if budget_exhausted else ""
        return f"渐进式研究完成：采纳 {accepted_count} 条证据，执行 {provider_searches} 次 provider 搜索。{suffix}"
    suffix = " The maximum number of research rounds was reached, with candidate queries left unexecuted." if budget_exhausted else ""
    return f"Progressive research complete: {accepted_count} evidence items accepted and {provider_searches} provider searches executed.{suffix}"
