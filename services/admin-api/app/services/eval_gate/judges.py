"""032-eval-gate: deterministic rule-based judges (spec 已定决策 #5).

Three proxies for the unmeasurable "hallucination rate":

- **引用支撑率** (citation_support): fraction of cases with non-empty
  ``expected_refs`` whose output mentions at least one expected source.
- **拒答正确率** (refusal_accuracy): fraction of ``expect_refusal`` cases that
  the model correctly refused.
- **任务成功率** (task_success): fraction of non-refusal cases whose output
  contains every expected phrase/keyword.

Rules are substring/pattern matches over the model output only — no LLM-as-judge
(YAGNI, phase 2).  The refusal signal vocabulary below mirrors the wording used
by chat-api's knowledge QA agent / citation resolver, so it stays aligned with
production refusal phrasing.
"""

from __future__ import annotations

import re
from typing import Any

from .models import EvalCaseResult


#: Phrases that indicate a refusal.  Sampled from production refusal phrasing
#: (chat-api knowledge agent + enterprise capability boundary messages).
REFUSAL_PHRASES: tuple[str, ...] = (
    "无法回答",
    "不能回答",
    "不便回答",
    "我无法提供",
    "我不能提供",
    "无法提供",
    "不予回答",
    "拒绝回答",
    "抱歉",
    "对不起",
    "很遗憾",
    "i cannot",
    "i can't",
    "i'm unable",
    "i am unable",
    "unable to answer",
    "cannot provide",
    "can't provide",
    "no information available",
    "not enough information",
    "insufficient information",
    "i don't know",
    "i do not know",
    "cannot answer",
    "can't answer",
)

#: Stronger refusal signal (used as a fallback when the phrase list alone
#: would be ambiguous).
REFUSAL_PATTERN = re.compile(
    r"(抱歉|无法|不能|拒绝|不予|没有足够信息|i\s*can(not|'t)|unable to|"
    r"cannot|do not know|don't know|not enough information)",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def is_refusal(output: str) -> bool:
    """True when the model output signals a refusal."""
    text = _normalise(output)
    if not text:
        return False
    if any(phrase in text for phrase in REFUSAL_PHRASES):
        return True
    return bool(REFUSAL_PATTERN.search(text))


def citation_supported(output: str, expected_refs: list[str]) -> bool | None:
    """Whether the output references any expected source.

    Returns ``None`` when there is no expected reference to check (those cases
    are excluded from the citation-support denominator — spec US2 edge case).
    """
    refs = [str(item).strip().lower() for item in (expected_refs or []) if str(item).strip()]
    if not refs:
        return None
    text = _normalise(output)
    for ref in refs:
        # A ref may be a document id (src-xxx), a citation id, or a source name.
        if ref and ref in text:
            return True
    return False


def task_successful(output: str, expectations: list[str]) -> bool | None:
    """Whether the output covers every expected point.

    AND semantics with case-insensitive substring matching (spec R-3): every
    expectation must appear verbatim.  A token-level fallback would silently
    loosen the judge (one matching word = pass) and inflate task success, so
    there is deliberately none.  ``expect_refusal`` cases return ``None`` —
    they are excluded from the task-success denominator.
    """
    expected = [str(item).strip() for item in (expectations or []) if str(item).strip()]
    if not expected:
        return None
    text = _normalise(output)
    if not text:
        return False
    return all(phrase.lower() in text for phrase in expected)


def judge_case(case: dict[str, Any], output: str) -> EvalCaseResult:
    """Produce a per-case judgement summary for one golden case."""
    case_id = str(case.get("_id") or case.get("id") or "")
    expect_refusal = bool(case.get("expect_refusal"))
    expectations = list(case.get("expectations") or [])
    expected_refs = list(case.get("expected_refs") or [])

    result = EvalCaseResult(case_id=case_id)
    if expect_refusal:
        result.kind = "refusal"
        result.refusal_accuracy = is_refusal(output)
        result.citation_support = citation_supported(output, expected_refs)
        result.task_success = None
        if result.refusal_accuracy:
            result.reasons.append("输出命中拒答信号")
        else:
            result.reasons.append("输出未命中拒答信号")
        if result.citation_support is not None:
            result.reasons.append("引用支撑判定：%s" % ("命中" if result.citation_support else "未命中"))
        return result

    # ordinary task case
    result.kind = "task"
    result.task_success = task_successful(output, expectations)
    result.citation_support = citation_supported(output, expected_refs)
    result.refusal_accuracy = None
    if result.task_success:
        result.reasons.append("输出覆盖全部期望要点")
    else:
        result.reasons.append("输出未覆盖全部期望要点")
    if result.citation_support is not None:
        result.reasons.append("引用支撑判定：%s" % ("命中" if result.citation_support else "未命中"))
    return result


def aggregate(case_results: list[EvalCaseResult]) -> dict[str, float]:
    """Compute the three headline metrics from per-case judgements.

    Denomination rules (spec 已定决策 #11):
    - citation_support denominator = cases with non-empty expected_refs
    - refusal_accuracy denominator = cases with ``expect_refusal``
    - task_success denominator = cases without ``expect_refusal``
    """
    citation_den = sum(1 for r in case_results if r.citation_support is not None)
    citation_num = sum(1 for r in case_results if r.citation_support)
    refusal_den = sum(1 for r in case_results if r.kind == "refusal")
    refusal_num = sum(1 for r in case_results if r.refusal_accuracy)
    task_den = sum(1 for r in case_results if r.task_success is not None)
    task_num = sum(1 for r in case_results if r.task_success)

    # Empty denominator -> ``None`` ("不适用"), not 0.0: a skill whose whole test
    # set carries no expected_refs must not be blocked for a metric that cannot
    # be measured (spec Edge Case: 空期望不参与分母).
    return {
        "citation_support": (citation_num / citation_den) if citation_den else None,
        "refusal_accuracy": (refusal_num / refusal_den) if refusal_den else None,
        "task_success": (task_num / task_den) if task_den else None,
    }