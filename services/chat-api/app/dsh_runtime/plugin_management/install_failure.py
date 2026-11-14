"""Interpret DSH package-manager failures without discarding their diagnostics."""

from __future__ import annotations

from typing import Any


def install_error_text(result: dict[str, Any]) -> str:
    error = result.get("error") or {}
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        return ": ".join(str(value) for value in (
            error.get("code"), error.get("diagnostic") or error.get("message") or error.get("reason"),
        ) if value) or "Plugin installation failed"
    return str(error)


def is_missing_registry_dependency(result: dict[str, Any]) -> bool:
    diagnostic = install_error_text(result)
    return "ERR_PNPM_NO_MATCHING_VERSION" in diagnostic or "No matching version found" in diagnostic
