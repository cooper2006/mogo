"""Webhook security (013 FR-13 / clarify OQ-4).

Inbound webhooks are authenticated with an **HMAC-SHA256** signature and protected
against replay by a **nonce cache** with a 5-minute window. Credentials are never
committed — they are injected via the environment / secret store (FR-8).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field

REPLAY_WINDOW_SECONDS = 300  # 5 minutes


class WebhookSignatureError(PermissionError):
    """Raised when a webhook signature is missing, malformed, or invalid."""


def sign_payload(*, secret: str, body: bytes, nonce: str, timestamp: int) -> str:
    """Compute the HMAC-SHA256 signature over ``nonce.timestamp.body``."""
    if not secret:
        raise WebhookSignatureError("webhook secret is not configured")
    message = f"{nonce}.{int(timestamp)}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(
    *,
    secret: str,
    body: bytes,
    nonce: str,
    timestamp: int,
    signature: str,
    now: int | None = None,
    window_seconds: int = REPLAY_WINDOW_SECONDS,
) -> None:
    """Verify a webhook signature, raising ``WebhookSignatureError`` on failure.

    Rejects:
    * a missing/empty signature;
    * a timestamp outside the replay window;
    * a signature that does not match (constant-time compare).
    """
    if not signature:
        raise WebhookSignatureError("missing signature")
    current = int(now if now is not None else time.time())
    if abs(current - int(timestamp)) > int(window_seconds):
        raise WebhookSignatureError("timestamp outside the replay window")
    expected = sign_payload(secret=secret, body=body, nonce=nonce, timestamp=timestamp)
    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("signature mismatch")


@dataclass
class NonceCache:
    """Short-lived nonce cache used to reject replayed webhooks (5-minute window)."""

    window_seconds: int = REPLAY_WINDOW_SECONDS
    _seen: dict[str, int] = field(default_factory=dict)

    def _evict(self, now: int) -> None:
        expired = [nonce for nonce, at in self._seen.items() if now - at > self.window_seconds]
        for nonce in expired:
            self._seen.pop(nonce, None)

    def check_and_store(self, nonce: str, *, now: int | None = None) -> bool:
        """Record ``nonce``; returns False when it is a replay.

        A repeated nonce within the window is a replay and must be rejected.
        """
        if not nonce:
            raise WebhookSignatureError("missing nonce")
        current = int(now if now is not None else time.time())
        self._evict(current)
        if nonce in self._seen:
            return False
        self._seen[nonce] = current
        return True

    def __len__(self) -> int:
        return len(self._seen)
