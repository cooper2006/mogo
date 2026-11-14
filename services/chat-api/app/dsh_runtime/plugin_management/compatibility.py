"""Classify the conversation capabilities exposed by an installed DSH bundle."""

from __future__ import annotations


def classify_conversation_tools(discovered: set[str], exposed: set[str]) -> tuple[str, str]:
    if not discovered:
        return "unsupported", "no_global_tool_detected"
    if discovered <= exposed:
        return "session_exposed", "invocation_not_verified"
    return "not_exposed", "tools_missing_from_session"
