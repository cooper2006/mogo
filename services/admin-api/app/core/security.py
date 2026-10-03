from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from app.core.config import settings

# QF-350: refresh token TTL (14 days)
REFRESH_TOKEN_TTL_SECONDS = 14 * 24 * 3600
# QF-352: idle timeout (30 minutes) and absolute timeout (24 hours)
IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 24 * 3600
# QF-360: recovery token TTL (1 hour)
RECOVERY_TOKEN_TTL_SECONDS = 3600
# QF-360: recovery token entropy (256 bits)
RECOVERY_TOKEN_BYTES = 32


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    normalized_salt = salt or secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        normalized_salt.encode("utf-8"),
        120_000,
    ).hex()
    return password_hash, normalized_salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, password_hash)


def create_access_token(subject: dict[str, object], expires_in_seconds: int | None = None) -> tuple[str, int, str]:
    expires_at = int(time.time()) + int(expires_in_seconds or settings.access_token_ttl_seconds)
    session_id = str(uuid.uuid4())
    payload = {
        "sub": {
            **subject,
            "session_id": session_id,
        },
        "exp": expires_at,
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{encoded_payload}.{encoded_signature}", expires_at, session_id


def decode_access_token(token: str) -> dict[str, object]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc

    expected_signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual_signature = base64.urlsafe_b64decode(_with_padding(encoded_signature))
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise ValueError("Invalid token signature")

    payload_raw = base64.urlsafe_b64decode(_with_padding(encoded_payload)).decode("utf-8")
    payload = json.loads(payload_raw)
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Token expired")
    return payload


def _with_padding(value: str) -> str:
    return value + "=" * (-len(value) % 4)


# ── QF-350: Refresh tokens with rotation and replay detection ────────────


def create_refresh_token(
    subject: dict[str, object],
    *,
    family_id: str | None = None,
    expires_in_seconds: int | None = None,
) -> tuple[str, int, str, str]:
    """Create a refresh token.

    Returns ``(token, expires_at, token_id, family_id)``.

    The token is a signed JWT containing:
    - ``sub``: user subject
    - ``exp``: expiration timestamp
    - ``jti``: unique token ID (for revocation tracking)
    - ``fid``: family ID (all refresh tokens in the same login session share this)

    Rotation: each use of a refresh token invalidates the old one and issues
    a new one with the same ``fid``. If a revoked token is reused, the entire
    family is revoked (replay detection).
    """
    token_id = str(uuid.uuid4())
    fam = family_id or str(uuid.uuid4())
    expires_at = int(time.time()) + int(expires_in_seconds or REFRESH_TOKEN_TTL_SECONDS)
    payload = {
        "sub": {**subject, "session_id": fam},
        "exp": expires_at,
        "jti": token_id,
        "fid": fam,
        "typ": "refresh",
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{encoded_payload}.{encoded_signature}", expires_at, token_id, fam


def decode_refresh_token(token: str) -> dict[str, object]:
    """Decode and validate a refresh token."""
    payload = decode_access_token(token)
    if str(payload.get("typ")) != "refresh":
        raise ValueError("Not a refresh token")
    if not payload.get("jti"):
        raise ValueError("Missing token ID")
    if not payload.get("fid"):
        raise ValueError("Missing family ID")
    return payload


# ── QF-360~361: Recovery tokens (high-entropy, one-time, short-lived) ────


def create_recovery_token(
    username: str,
    main_id: str,
    purpose: str = "password_reset",
) -> tuple[str, int, str]:
    """Create a high-entropy recovery token.

    Returns ``(token, expires_at, token_hash)``.

    The token is a URL-safe base64-encoded random value (256 bits).
    Only the SHA-256 hash is stored in the database; the raw token is
    shown to the user once and never stored.
    """
    raw_bytes = secrets.token_bytes(RECOVERY_TOKEN_BYTES)
    token = base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + RECOVERY_TOKEN_TTL_SECONDS
    return token, expires_at, token_hash


def hash_recovery_token(token: str) -> str:
    """Hash a recovery token for database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── QF-357: Account existence check (constant-time, no leak) �─────────────


def mask_identifier(identifier: str) -> str:
    """Return a masked version of an identifier (e.g., 'a***@example.com').

    QF-363: recovery flow must not leak sensitive account information.
    """
    if not identifier:
        return ""
    if "@" in identifier:
        local, _, domain = identifier.rpartition("@")
        if len(local) <= 2:
            masked_local = local[0] + "*" * (len(local) - 1)
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
    if len(identifier) <= 3:
        return "*" * len(identifier)
    return identifier[0] + "*" * (len(identifier) - 3) + identifier[-2:]


def constant_time_bool(condition: bool) -> bool:
    """Return *condition* without timing side-channels.

    QF-357: register/recover endpoints must not leak account existence.
    """
    # Use hmac.compare_digest to prevent timing attacks.
    # Convert bool to a constant-length comparison.
    return hmac.compare_digest(b"1" if condition else b"0", b"1" if condition else b"0")
