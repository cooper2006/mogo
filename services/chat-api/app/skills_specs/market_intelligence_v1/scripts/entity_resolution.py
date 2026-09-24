"""Legal-entity resolution helpers for market intelligence."""

from __future__ import annotations

import re
from typing import Iterable


_LEGAL_SUFFIXES = (
    "有限公司", "股份有限公司", "集团", "科技", "网络", "信息技术",
    "inc.", "inc", "ltd.", "ltd", "llc", "corp.", "corporation", "gmbh",
)


def normalize_entity_name(name: str) -> str:
    """Strip legal suffixes and punctuation to compare entity names."""
    value = str(name or "").strip().lower()
    for suffix in _LEGAL_SUFFIXES:
        value = value.replace(suffix, "")
    return re.sub(r"[\s\-_/（）()]+", "", value)


def same_entity(left: str, right: str) -> bool:
    """Whether two mentions plausibly refer to the same legal entity."""
    a, b = normalize_entity_name(left), normalize_entity_name(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def resolve_entity(candidate: str, known: Iterable[str]) -> str | None:
    """Return the first known entity matching ``candidate``, else ``None``."""
    for entity in known:
        if same_entity(candidate, entity):
            return entity
    return None
