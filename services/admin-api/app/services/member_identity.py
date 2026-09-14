from __future__ import annotations

import re
from typing import Any, Mapping


_MOBILE_PATTERN = re.compile(r"^(?:\+?86[- ]?)?1[3-9]\d{9}$")


def public_identity(values: Mapping[str, Any] | None, *, user_id: str = "") -> dict[str, str]:
    identity = values or {}
    name = str(identity.get("displayName") or identity.get("name") or "").strip()
    if "@" in name or _MOBILE_PATTERN.fullmatch(name):
        name = ""
    return {
        "userId": str(identity.get("userId") or identity.get("user_id") or user_id or ""),
        "displayName": name,
    }
