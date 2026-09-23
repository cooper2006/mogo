"""PII recognizers and redaction strategy engine (T019 / T020).

Five PII classes, each with its own regex recognizer (T019):

=================  =========================
class            recognizer
=================  =========================
private_key      PEM blocks + common key prefixes
id_card          18-digit Chinese ID (checksum-agnostic)
bank_card        16-19 digit card numbers
phone            CN mobile / CN landline
email            RFC-style address
=================  =========================

Four strategies (T020) applied per PII class by the policy engine:

* ``mask``     keep a readable prefix/suffix, mask the middle
               (phone -> ``138****0000``)
* ``remove``   replace with an empty string (the value never leaves this module)
* ``hash``     replace with a truncated SHA-256 fingerprint (traceable, not
               recoverable)
* ``abstract`` replace with a typed placeholder (``[EMAIL]``)

The policy table lives in the ``pii_policies`` collection: a global default row
(``tenant_id=""``, seeded by ``schema._seed_defaults``) plus optional tenant
override rows. An override requires 006 authorization at the admin boundary
(enforced at the CRUD endpoint) and is audited (FR-10).

Recognizers are ordered by specificity: keys first, then longer digit patterns,
so that e.g. an ID card number is not partially consumed as a bank card or a
phone number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

PII_TYPES: tuple[str, ...] = ("private_key", "id_card", "bank_card", "phone", "email")

STRATEGIES: tuple[str, ...] = ("mask", "remove", "hash", "abstract")

# Default strategy per class (clarify OQ-3; mirrored in schema.DEFAULT_PII_POLICY).
DEFAULT_STRATEGY: dict[str, str] = {
    "private_key": "remove",
    "id_card": "hash",
    "bank_card": "mask",
    "phone": "mask",
    "email": "abstract",
}

_ABSTRACT_PLACEHOLDERS = {
    "private_key": "[KEY]",
    "id_card": "[ID]",
    "bank_card": "[CARD]",
    "phone": "[PHONE]",
    "email": "[EMAIL]",
}


@dataclass(frozen=True)
class PIIRecognizer:
    type: str
    pattern: "re.Pattern[str]"


_PII_RECOGNIZERS: tuple[PIIRecognizer, ...] = (
    # PEM blocks and common key prefixes must come first (most specific).
    PIIRecognizer(
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    ),
    PIIRecognizer(
        "private_key",
        re.compile(r"\b(AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|ghp_[0-9A-Za-z]{36}|sk-[0-9A-Za-z]{20,})\b"),
    ),
    # 18-digit national ID (17 digits + check char) before shorter digit patterns.
    PIIRecognizer("id_card", re.compile(r"\b\d{17}[\dXx]\b")),
    PIIRecognizer("bank_card", re.compile(r"\b\d{16,19}\b")),
    # CN mobile (11 digits, leading 1[3-9]) and CN landline with area code.
    PIIRecognizer("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    PIIRecognizer("phone", re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")),
    PIIRecognizer("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)

# Recognizer order must stay most-specific-first; keep this list in sync.
_RECOGNIZER_ORDER: tuple[str, ...] = tuple(rec.type for rec in _PII_RECOGNIZERS)


def find_pii(text: Optional[str], types: Optional[list[str]] = None) -> list[tuple[str, int, int, str]]:
    """Scan ``text`` and return non-overlapping ``(pii_type, start, end, value)`` hits.

    Hits are sorted by position; when two recognizers overlap on the same span
    the earlier (more specific) one in recognizer order wins.
    """
    if not text:
        return []
    allowed = set(types) if types else None
    taken: list[tuple[int, int, str, str]] = []
    for index, recognizer in enumerate(_PII_RECOGNIZERS):
        if allowed is not None and recognizer.type not in allowed:
            continue
        for match in recognizer.pattern.finditer(text):
            start, end = match.span()
            value = match.group(0)
            # Reject overlaps with an already-claimed (earlier, more specific) hit.
            if any(not (end <= s or start >= e) for s, e, _, _ in taken):
                continue
            taken.append((start, end, recognizer.type, value))
    taken.sort(key=lambda item: item[0])
    return [(t, s, e, v) for s, e, t, v in taken]


def _mask_digits(value: str, keep_tail: int = 4) -> str:
    """Mask the middle of a digit string, keeping the first 3 and last ``keep_tail``."""
    if len(value) <= keep_tail + 3:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - keep_tail - 3) + value[-keep_tail:]


def _abstract_digits(value: str) -> str:
    return value[:3] + "*" * max(0, len(value) - 3)


def apply_strategy(value: str, pii_type: str, strategy: str) -> str:
    """Apply one strategy to one value; unknown strategies fall back to ``mask``."""
    strategy = strategy if strategy in STRATEGIES else "mask"
    if strategy == "remove":
        return ""
    if strategy == "hash":
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"{digest[:12]}…"
    if strategy == "abstract":
        if pii_type == "phone":
            # Keep the leading 3 / trailing 4 so support can still reach out.
            digits = "".join(ch for ch in value if ch.isdigit())
            if len(digits) >= 7:
                return _abstract_digits(digits)
            return _ABSTRACT_PLACEHOLDERS.get(pii_type, "[PII]")
        return _ABSTRACT_PLACEHOLDERS.get(pii_type, "[PII]")
    # mask
    if pii_type in ("bank_card", "id_card", "phone"):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return _mask_digits(digits, keep_tail=4 if pii_type != "phone" else 4)
    # Generic fallback for non-digit classes: keep first/last 2 chars.
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def redact_text(text: Optional[str], policies: Optional[dict[str, str]] = None) -> str:
    """Find and redact PII in ``text`` using per-class strategies.

    ``policies`` maps PII class -> strategy; missing classes fall back to
    :data:`DEFAULT_STRATEGY`. The function never returns the original PII value
    for any class whose effective strategy is not a lossy one (i.e. any
    strategy other than a pass-through; every supported strategy is lossy).
    """
    if not text:
        return text or ""
    effective = dict(DEFAULT_STRATEGY)
    if policies:
        for pii_type, strategy in policies.items():
            if pii_type in PII_TYPES and strategy in STRATEGIES:
                effective[str(pii_type)] = strategy

    hits = find_pii(text, [t for t in PII_TYPES if effective.get(t, "mask") != "pass_through"])
    if not hits:
        return text

    result: list[str] = []
    cursor = 0
    for pii_type, start, end, value in hits:
        result.append(text[cursor:start])
        result.append(apply_strategy(value, pii_type, effective.get(pii_type, "mask")))
        cursor = end
    result.append(text[cursor:])
    return "".join(result)


def fingerprint(value: str) -> str:
    """Stable hash fingerprint for audit traceability (never the plaintext)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
