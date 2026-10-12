"""FR-19 (QF-650/651–656) 敏感字段加密.

替换 :mod:`app.core.encryption` 中的自研「伪 AES-GCM」（BLAKE2b 流密码，见
QualityForge SEC-03）：**使用 `cryptography` 库的原生 AES-256-GCM**，
12 字节随机 nonce，16 字节认证标签由库内置计算。

密文格式（base64url，无 padding）：

.. code-block:: text

    v1 | nonce(12) | ciphertext || tag

- ``v1`` — 版本号，为后续算法/密钥轮换预留；
- 认证标签由 AESGCM 追加在密文末尾；
- ``AAD``（关联认证数据）= ``purpose``，防止同一密钥下不同字段的密文被互换。

密钥来源：:class:`~app.security.kms.KMSProvider`，实际使用其
:meth:`data_key_for` 派生出的数据密钥（主密钥与数据密钥分离）。
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:  # pragma: no cover
    from .kms import KMSProvider

VERSION_PREFIX = b"v1"
NONCE_SIZE = 12  # AES-GCM 推荐 nonce 长度
GCM_TAG_SIZE = 16
MAX_PLAINTEXT_BYTES = 1024 * 1024  # 1MB：敏感字段是小字符串，超限行大概率是误用

SUPPORTED_VERSIONS: tuple[bytes, ...] = (VERSION_PREFIX,)


class EncryptionError(ValueError):
    """加密/解密失败（含篡改检测）。"""


class _StaticKms:
    """测试/迁移用的最小 KMSProvider 替身。"""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) < 1:
            raise ValueError("master key must be non-empty")
        self._master_key = master_key

    def get_master_key(self) -> bytes:
        return self._master_key

    def data_key_for(self, purpose: str) -> bytes:
        from .kms import derive_data_key

        return derive_data_key(self._master_key, purpose=purpose)

    def describe(self) -> dict[str, object]:
        return {"provider": "static", "master_key_bytes": len(self._master_key)}


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(data: str) -> bytes:
    if not isinstance(data, str):
        raise EncryptionError("ciphertext blob must be a string")
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as exc:
        raise EncryptionError(f"malformed ciphertext: {exc}") from exc


def encrypt_value(
    plaintext: str | bytes,
    kms: "KMSProvider",
    *,
    purpose: str,
    aad: bytes | None = None,
) -> str:
    """加密一个敏感字段，返回 base64url 字符串（FR-19）。

    Args:
        plaintext: 待加密内容。字符串按 UTF-8 编码。
        kms: 密钥提供方；实际数据密钥 = ``kms.data_key_for(purpose)``。
        purpose: 用途标识（如 ``"mfa_secret"`` / ``"api_key"``），同时作为 AAD
            并参与数据密钥派生——不同用途的密文不可互换。
        aad: 附加认证数据，默认取 ``purpose``。

    Raises:
        EncryptionError: 明文为空、超过上限、或非字符串/bytes。
    """
    if purpose is None or not str(purpose).strip():
        raise EncryptionError("purpose is required")
    purpose_s = str(purpose)

    if isinstance(plaintext, str):
        data = plaintext.encode("utf-8")
    elif isinstance(plaintext, (bytes, bytearray)):
        data = bytes(plaintext)
    else:
        raise EncryptionError(f"unsupported plaintext type: {type(plaintext).__name__}")
    if not data:
        raise EncryptionError("refusing to encrypt empty plaintext")
    if len(data) > MAX_PLAINTEXT_BYTES:
        raise EncryptionError(
            f"plaintext too large: {len(data)} bytes > {MAX_PLAINTEXT_BYTES}; "
            "sensitive fields should be short strings"
        )

    key = kms.data_key_for(purpose_s)
    if len(key) != 32:  # pragma: no cover - defensive
        raise EncryptionError(f"unexpected data key length: {len(key)}")

    nonce = os.urandom(NONCE_SIZE)
    blob = AESGCM(key).encrypt(nonce, data, aad if aad is not None else purpose_s.encode("utf-8"))
    return _b64_encode(VERSION_PREFIX + nonce + blob)


def decrypt_value(
    ciphertext: str,
    kms: "KMSProvider",
    *,
    purpose: str,
    aad: bytes | None = None,
) -> bytes:
    """解密 :func:`encrypt_value` 产出的密文。

    Raises:
        EncryptionError: 版本不支持、格式非法、或**认证标签校验失败（内容被篡改）**。
    """
    if purpose is None or not str(purpose).strip():
        raise EncryptionError("purpose is required")
    purpose_s = str(purpose)

    raw = _b64_decode(ciphertext)
    if len(raw) <= len(VERSION_PREFIX) + NONCE_SIZE + GCM_TAG_SIZE:
        raise EncryptionError("ciphertext blob is too short")

    version = raw[: len(VERSION_PREFIX)]
    if version not in SUPPORTED_VERSIONS:
        raise EncryptionError(f"unsupported ciphertext version: {version!r}")

    body = raw[len(VERSION_PREFIX) :]
    nonce, payload = body[:NONCE_SIZE], body[NONCE_SIZE:]
    key = kms.data_key_for(purpose_s)
    try:
        return AESGCM(key).decrypt(nonce, payload, aad if aad is not None else purpose_s.encode("utf-8"))
    except InvalidTag as exc:
        # 认证失败 = 密文被篡改、密钥错误或 purpose 不匹配。统一成 EncryptionError，
        # 不向调用方泄露是哪一种（避免成为密码分析 oracle）。
        raise EncryptionError("ciphertext authentication failed (tampered, wrong key, or wrong purpose)") from exc


def decrypt_text(
    ciphertext: str,
    kms: "KMSProvider",
    *,
    purpose: str,
    aad: bytes | None = None,
) -> str:
    """解密并返回 UTF-8 字符串。"""
    return decrypt_value(ciphertext, kms, purpose=purpose, aad=aad).decode("utf-8")


def is_encrypted_blob(value: object) -> bool:
    """判断一个值是否是本模块产出的密文（用于幂等加密与迁移检测）。"""
    if not isinstance(value, str):
        return False
    try:
        raw = _b64_decode(value)
    except EncryptionError:
        return False
    return raw.startswith(VERSION_PREFIX) and len(raw) > len(VERSION_PREFIX)


def reencrypt(
    ciphertext: str,
    kms: "KMSProvider",
    *,
    purpose: str,
    aad: bytes | None = None,
) -> str:
    """用当前密钥重新加密（密钥轮换用）。"""
    plaintext = decrypt_value(ciphertext, kms, purpose=purpose, aad=aad)
    return encrypt_value(plaintext, kms, purpose=purpose, aad=aad)


def decrypt_optional(
    ciphertext: str | None,
    kms: "KMSProvider",
    *,
    purpose: str,
    aad: bytes | None = None,
) -> str | None:
    """宽容解密：None/空串/非密文原样返回，便于渐进式迁移。"""
    if not ciphertext:
        return ciphertext if isinstance(ciphertext, str) else None
    if not is_encrypted_blob(ciphertext):
        return ciphertext
    return decrypt_text(ciphertext, kms, purpose=purpose, aad=aad)


__all__ = [
    "AESGCM",
    "EncryptionError",
    "GCM_TAG_SIZE",
    "MAX_PLAINTEXT_BYTES",
    "NONCE_SIZE",
    "SUPPORTED_VERSIONS",
    "VERSION_PREFIX",
    "decrypt_optional",
    "decrypt_text",
    "decrypt_value",
    "encrypt_value",
    "is_encrypted_blob",
    "reencrypt",
]
