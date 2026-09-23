"""Low-entropy secret detection (002 FR-7 / clarify OQ-2).

A token is flagged as a *suspected secret* when **both** hold:

1. Shannon entropy >= 3.5 bits/char **and** length >= 16 (the low-entropy heuristic);
2. it matches one of the known credential prefixes (``sk-`` / ``ghp_`` / ``AKIA`` /
   ``Bearer `` ...).

The dual check keeps ordinary long document ids from being flagged. A whitelist
and manual marks (FR-10) suppress known false positives.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional

# Entropy / length thresholds (clarify OQ-2).
ENTROPY_THRESHOLD_BITS_PER_CHAR = 3.5
MIN_SECRET_LENGTH = 16

# Known credential prefixes -> a label for the audit trail.
PREFIX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{16,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{12,}")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}")),
)

# Generic long token candidate (letters/digits/base64-ish, no spaces).
_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/=_\-]{16,}")


@dataclass(frozen=True)
class SecretMatch:
    """A suspected secret found in text."""

    value: str
    label: str            # which prefix rule matched, or "low_entropy"
    start: int
    end: int


def shannon_entropy(text: str) -> float:
    """Shannon entropy in bits per character (0.0 for empty text)."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def is_high_entropy(value: str) -> bool:
    """Whether ``value`` passes the entropy + length heuristic."""
    return len(value) >= MIN_SECRET_LENGTH and shannon_entropy(value) >= ENTROPY_THRESHOLD_BITS_PER_CHAR


def _match_prefix(value: str) -> Optional[str]:
    for label, pattern in PREFIX_PATTERNS:
        if pattern.search(value):
            return label
    return None


def detect_secrets(
    text: str,
    *,
    whitelist: Iterable[str] = (),
    marked: Iterable[str] = (),
) -> list[SecretMatch]:
    """Find suspected secrets in ``text``.

    A candidate is reported when it matches a credential prefix, **or** when it is
    both high-entropy and long. Entries in ``whitelist`` / ``marked`` (FR-10) are
    never reported.
    """
    if not text:
        return []
    suppressed = {item for item in whitelist if item} | {item for item in marked if item}
    matches: list[SecretMatch] = []

    # Pass 1: explicit credential prefixes (highest confidence).
    for label, pattern in PREFIX_PATTERNS:
        for found in pattern.finditer(text):
            value = found.group(0).strip()
            if value in suppressed:
                continue
            matches.append(
                SecretMatch(value=value, label=label, start=found.start(), end=found.end())
            )

    def _overlaps_known(start: int, end: int) -> bool:
        # A generic candidate is skipped if it overlaps (or is contained in) an
        # already-matched credential, so the same token is never reported twice.
        return any(not (end <= item.start or start >= item.end) for item in matches)

    # Pass 2: generic high-entropy candidates not already covered by a prefix.
    for found in _CANDIDATE_RE.finditer(text):
        value = found.group(0)
        if value in suppressed:
            continue
        if _overlaps_known(found.start(), found.end()):
            continue
        if not is_high_entropy(value):
            continue
        matches.append(
            SecretMatch(value=value, label="low_entropy", start=found.start(), end=found.end())
        )

    matches.sort(key=lambda item: item.start)
    return matches


def contains_secret(text: str, **kwargs: object) -> bool:
    return bool(detect_secrets(text, **kwargs))  # type: ignore[arg-type]
