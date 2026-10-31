from __future__ import annotations


_ENGLISH_MESSAGES = {
    "生成失败": "Workflow generation failed",
    "模型未返回可用步骤": "The model returned no usable steps",
    "模型未返回可用节点": "The model returned no usable nodes",
    "润色失败": "Failed to refine the node requirement",
    "模型未返回可用节点要求": "The model returned no usable node requirement",
    "检查失败": "Workflow check failed",
    "规则检测通过，LLM 审查暂不可用": "Rule checks passed; LLM review is unavailable",
    "规则检测未通过": "Rule checks failed",
    "规则检测已通过，但 LLM 审查暂不可用。": "Rule checks passed, but LLM review is unavailable.",
}


def localized_workflow_message(message: str, accept_language: str | None, fallback: str) -> str:
    language = (accept_language if isinstance(accept_language, str) else "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    if not language.startswith("en"):
        return message
    translated = _ENGLISH_MESSAGES.get(message, message)
    return fallback if any("\u3400" <= char <= "\u9fff" for char in translated) else translated
