"""TOTP (Time-based One-Time Password) implementation for MFA (QF-342~347).

Implements RFC 6238 using HMAC-SHA1 with a 30-second step and 6-digit codes.
No external dependencies — pure stdlib.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_SECRET_BYTES = 20
TOTP_ISSUER = "MOVO Admin"


def generate_secret() -> str:
    """Generate a base32-encoded random TOTP secret."""
    raw = _os.urandom(TOTP_SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _base32_decode(secret: str) -> bytes:
    """Decode a base32 secret string to raw bytes."""
    secret = secret.strip().rstrip("=")
    padding = (8 - len(secret) % 8) % 8
    padded = secret + "=" * padding
    return base64.b32decode(padded, casefold=True)


def compute_totp(secret: str, *, step: int = 0, time_offset: int = 0) -> str:
    """Compute the TOTP code for *secret* at the current time (or offset).

    *step* is the number of 30-second windows from now (negative = past).
    *time_offset* is a legacy parameter for drift tolerance.
    """
    counter = int(time.time() // TOTP_STEP_SECONDS) + step
    key = _base32_decode(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10 ** TOTP_DIGITS)
    return str(code).zfill(TOTP_DIGITS)


def verify_totp(secret: str, token: str, *, window: int = 1) -> bool:
    """Verify *token* against *secret*, allowing ±*window* steps of drift."""
    target = token.strip()
    if not target or len(target) != TOTP_DIGITS:
        return False
    for step in range(-window, window + 1):
        if hmac.compare_digest(compute_totp(secret, step=step), target):
            return True
    return False


def totp_uri(username: str, secret: str) -> str:
    """Build the otpauth:// URI for QR code provisioning."""
    return (
        f"otpauth://totp/{TOTP_ISSUER}:{username}"
        f"?secret={secret}&issuer={TOTP_ISSUER}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"
    )


# Convenience alias for tests and callers that prefer the ``secrets`` module name.
_os = __import__("os")
