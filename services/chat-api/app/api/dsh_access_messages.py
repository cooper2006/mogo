"""Localized fixed access denial for desktop code capabilities."""

from __future__ import annotations


def code_capability_denied(accept_language: str | None) -> str:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    if language.startswith("en"):
        return "Code generation is not enabled for your position role; this task was not run"
    return "当前岗位未开通代码生成能力，本次任务未执行"
