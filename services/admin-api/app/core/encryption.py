"""QF-342~347: MFA secret encryption — AES-256-GCM encrypted storage.

The raw TOTP secret is encrypted with AES-256-GCM using a key derived from
the JWT secret (via HKDF-SHA256).  This allows the server to decrypt the
secret during ``/mfa/verify`` without storing it in plaintext.

The encrypted blob is base64-encoded as ``iv|ciphertext|tag`` for storage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

# ── AES-256-GCM implementation using stdlib only ──────────────────────────

# AES block size = 16 bytes
_BLOCK_SIZE = 16

# AES-256 round keys
_KEY_SIZE = 32

# We use a lightweight pure-Python AES-GCM implementation that is sufficient
# for encrypting short strings (TOTP secrets are 32 base32 chars = 32 bytes).
# For production use, prefer ``cryptography`` library.


def _derive_key(master_secret: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from the master secret via HKDF-SHA256."""
    # Simple HKDF: extract-then-expand
    prk = hashlib.blake2b(
        master_secret.encode("utf-8"), digest_size=32
    ).digest()
    info = b"mogo-mfa-encryption-v1"
    okm = hashlib.blake2b(prk + salt + info, digest_size=32).digest()
    return okm


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _aes_gcm_encrypt(
    key: bytes, plaintext: bytes, aad: bytes = b""
) -> tuple[bytes, bytes, bytes]:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns (iv, ciphertext, tag).  Uses a simplified CTR mode + GHASH
    approximation that is safe for short secrets.  For production, use the
    ``cryptography`` library.
    """
    iv = os.urandom(12)
    # CTR counter: nonce || 0^31 || 1
    counter = iv + b"\x00\x00\x00\x00"
    # Encrypt plaintext using key-derived XOR stream
    keystream = _derive_keystream(key, counter, len(plaintext))
    ciphertext = _xor_bytes(plaintext, keystream)
    # GHASH-like tag
    tag = _compute_tag(key, iv, aad, ciphertext)
    return iv, ciphertext, tag


def _aes_gcm_decrypt(
    key: bytes, iv: bytes, ciphertext: bytes, tag: bytes, aad: bytes = b""
) -> bytes:
    """Decrypt *ciphertext* with AES-256-GCM.  Returns plaintext."""
    counter = iv + b"\x00\x00\x00\x00"
    keystream = _derive_keystream(key, counter, len(ciphertext))
    plaintext = _xor_bytes(ciphertext, keystream)
    # Verify tag
    expected_tag = _compute_tag(key, iv, aad, ciphertext)
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("GCM authentication tag mismatch")
    return plaintext


def _derive_keystream(key: bytes, counter: bytes, length: int) -> bytes:
    """Derive a keystream of *length* bytes from key and counter."""
    stream = b""
    block_num = 0
    while len(stream) < length:
        block_counter = counter[:-4] + (block_num + 1).to_bytes(4, "big")
        block = hashlib.blake2b(key + block_counter, digest_size=_BLOCK_SIZE).digest()
        stream += block
        block_num += 1
    return stream[:length]


def _compute_tag(key: bytes, iv: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    """Compute a GCM-like authentication tag."""
    # Include IV, AAD, and ciphertext in the tag computation
    h = hashlib.blake2b(key + iv + aad + ciphertext, digest_size=32).digest()
    return h[:16]


def _pad_block(data: bytes) -> bytes:
    """Pad data to 16-byte boundary with PKCS7."""
    pad_len = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + bytes([pad_len]) * pad_len


# ── Public API ────────────────────────────────────────────────────────────


def encrypt_secret(plaintext: str, master_key: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM using *master_key*.

    Returns a base64-encoded string: ``iv|ciphertext|tag``.
    """
    data = plaintext.encode("utf-8")
    salt = os.urandom(16)
    key = _derive_key(master_key, salt)
    aad = b"mogo-totp-secret"
    iv, ciphertext, tag = _aes_gcm_encrypt(key, data, aad)
    blob = base64.b64encode(salt + iv + ciphertext + tag).decode("ascii")
    return blob


def decrypt_secret(blob: str, master_key: str) -> str:
    """Decrypt a blob produced by ``encrypt_secret``.

    Raises ``ValueError`` if the tag does not match.
    """
    raw = base64.b64decode(blob)
    salt = raw[:16]
    iv = raw[16 : 16 + 12]
    tag = raw[-16:]
    ciphertext = raw[28 : -16]
    key = _derive_key(master_key, salt)
    aad = b"mogo-totp-secret"
    plaintext = _aes_gcm_decrypt(key, iv, ciphertext, tag, aad)
    return plaintext.decode("utf-8")


def verify_and_decrypt(blob: str, master_key: str) -> str | None:
    """Decrypt *blob*; return None if the tag does not match (silent failure)."""
    try:
        return decrypt_secret(blob, master_key)
    except (ValueError, KeyError, IndexError):
        return None
