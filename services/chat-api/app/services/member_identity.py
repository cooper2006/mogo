from __future__ import annotations

import re
from typing import Any, Mapping


_MOBILE_PATTERN = re.compile(r"^(?:\+?86[- ]?)?1[3-9]\d{9}$")


def is_private_identifier(value: Any) -> bool:
    """Return whether an account identifier should stay out of public UI."""
    text = str(value or "").strip()
    return bool(text and ("@" in text or _MOBILE_PATTERN.fullmatch(text)))


def public_display_name(values: Mapping[str, Any]) -> str:
    """Resolve an explicitly public member name without exposing login details."""
    for field in ("name", "display_name", "nickname", "displayName"):
        value = str(values.get(field) or "").strip()
        if value and not is_private_identifier(value):
            return value
    for field in ("login_name", "username"):
        value = str(values.get(field) or "").strip()
        if value and not is_private_identifier(value):
            return value
    return ""


def public_identity(values: Mapping[str, Any] | None, *, user_id: str = "") -> dict[str, str]:
    identity = values or {}
    return {
        "userId": str(identity.get("userId") or identity.get("user_id") or user_id or ""),
        "displayName": public_display_name(identity),
    }


def masked_account_identifier(value: Any) -> str:
    """Keep directory entries distinguishable without returning raw phone/email."""
    text = str(value or "").strip()
    if _MOBILE_PATTERN.fullmatch(text):
        prefix = "+86 " if text.startswith(("+86", "86")) else ""
        digits = re.sub(r"\D", "", text)[-11:]
        return f"{prefix}{digits[:3]}****{digits[-4:]}"
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}" if domain else ""
    return text
