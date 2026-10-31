"""Language specific fallback text for workflow check results."""

from __future__ import annotations


_FALLBACKS = {
    "logic_label": ("需要澄清", "Needs clarification"),
    "logic_summary": ("模型未返回明确的逻辑说明。", "The model did not provide a clear logic explanation."),
    "conclusion": ("当前业务逻辑仍需进一步澄清。", "The current business logic needs further clarification."),
    "script_review_summary": ("LLM 未返回明确审查结论。", "The LLM did not provide a clear review conclusion."),
}


def workflow_check_fallback(key: str, accept_language: str | None) -> str:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    chinese, english = _FALLBACKS[key]
    return english if language.startswith("en") else chinese


def workflow_check_language_instruction(accept_language: str | None) -> str:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    return " Write all user-visible descriptions in English." if language.startswith("en") else " Write all user-visible descriptions in Chinese."
