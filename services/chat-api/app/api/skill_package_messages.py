"""Localized fixed errors for Skill package upload endpoints."""

from __future__ import annotations


_MESSAGES = {
    "zip_required": ("请选择 ZIP 格式的 Skill 安装包", "Select a Skill installation package in ZIP format"),
    "organization_install_forbidden": ("只有企业管理后台可以安装企业 Skill", "Only the organization admin console can install organization Skills"),
}


def skill_package_message(code: str, accept_language: str | None) -> str:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    chinese, english = _MESSAGES[code]
    return english if language.startswith("en") else chinese
