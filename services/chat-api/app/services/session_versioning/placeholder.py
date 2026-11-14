"""Reversible placeholder substitution for secrets (002 FR-7 / FR-8).

When a suspected secret is detected at commit/share time it is replaced by a
**reversible placeholder** of the form ``{{secret:<id>}}``. The placeholder is
only dereferenceable by the session owner or a full-access administrator, and each
dereference is audited (FR-8).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from .secrets import detect_secrets

PLACEHOLDER_OPEN = "{{secret:"
PLACEHOLDER_CLOSE = "}}"

# Roles allowed to dereference a placeholder (FR-8).
DEREFERENCE_ROLES = frozenset({"owner", "full_access_admin"})


@dataclass
class PlaceholderStore:
    """In-memory mapping id -> original secret, scoped to one session."""

    _secrets: dict[str, str] = field(default_factory=dict)

    def put(self, secret: str) -> str:
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        self._secrets.setdefault(digest, secret)
        return digest

    def get(self, token_id: str) -> str | None:
        return self._secrets.get(token_id)

    def token(self, secret: str) -> str:
        return f"{PLACEHOLDER_OPEN}{self.put(secret)}{PLACEHOLDER_CLOSE}"

    @property
    def size(self) -> int:
        return len(self._secrets)


def reference(text: str, store: PlaceholderStore, **detect_kwargs: object) -> tuple[str, list[str]]:
    """Replace every detected secret in ``text`` with a placeholder.

    Returns the redacted text and the list of placeholder ids that were inserted.
    """
    matches = detect_secrets(text, **detect_kwargs)  # type: ignore[arg-type]
    if not matches:
        return text, []
    redacted = text
    ids: list[str] = []
    # Replace from the end so earlier offsets stay valid.
    for match in sorted(matches, key=lambda item: item.start, reverse=True):
        token_id = store.put(match.value)
        ids.append(token_id)
        redacted = redacted[: match.start] + f"{PLACEHOLDER_OPEN}{token_id}{PLACEHOLDER_CLOSE}" + redacted[match.end :]
    return redacted, list(reversed(ids))


class DereferenceDenied(PermissionError):
    """Raised when the caller may not dereference a placeholder."""


def dereference(
    text: str,
    store: PlaceholderStore,
    *,
    role: str,
    audit: list[dict[str, object]] | None = None,
    actor: str = "",
) -> str:
    """Restore placeholders in ``text`` for an authorized caller.

    Only ``owner`` / ``full_access_admin`` may dereference (FR-8); every
    dereference is appended to ``audit`` when a list is supplied.
    """
    if role not in DEREFERENCE_ROLES:
        raise DereferenceDenied(f"role {role!r} may not dereference placeholders")

    result = text
    index = 0
    while True:
        start = result.find(PLACEHOLDER_OPEN, index)
        if start == -1:
            break
        end = result.find(PLACEHOLDER_CLOSE, start + len(PLACEHOLDER_OPEN))
        if end == -1:
            break
        token_id = result[start + len(PLACEHOLDER_OPEN) : end]
        secret = store.get(token_id)
        if secret is None:
            index = end + len(PLACEHOLDER_CLOSE)
            continue
        if audit is not None:
            audit.append({"action": "dereference", "token_id": token_id, "actor": actor})
        result = result[:start] + secret + result[end + len(PLACEHOLDER_CLOSE) :]
        index = start + len(secret)
    return result


def placeholder_ids(text: str) -> list[str]:
    """List the placeholder ids present in ``text``."""
    ids: list[str] = []
    index = 0
    while True:
        start = text.find(PLACEHOLDER_OPEN, index)
        if start == -1:
            break
        end = text.find(PLACEHOLDER_CLOSE, start + len(PLACEHOLDER_OPEN))
        if end == -1:
            break
        ids.append(text[start + len(PLACEHOLDER_OPEN) : end])
        index = end + len(PLACEHOLDER_CLOSE)
    return ids


def redacted_text_is_clean(text: str, originals: Iterable[str]) -> bool:
    """Whether none of the ``originals`` appear in plaintext in ``text``."""
    return all(original and original not in text for original in originals)
