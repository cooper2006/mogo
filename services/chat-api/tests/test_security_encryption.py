"""FR-19 (QF-650/656) 敏感字段加密测试.

覆盖：AES-256-GCM 往返、密文格式与随机性、篡改检测、purpose 绑定（AAD）、
长度/空值防护、密钥轮换、可选解密、密文识别。

使用真实 ``cryptography`` 库，而非自研实现（替换 SEC-03 的伪 AES-GCM）。
"""

from __future__ import annotations

import base64

import pytest

from app.security import encryption as enc
from app.security import kms


MASTER_KEY = b"unit-test-master-key-1234567890"


@pytest.fixture()
def kms_provider():
    return kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: MASTER_KEY.decode()})


# ---------------------------------------------------------------------------
# 基本往返
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(kms_provider):
    blob = enc.encrypt_value("super-secret-value", kms_provider, purpose="mfa_secret")
    assert enc.decrypt_text(blob, kms_provider, purpose="mfa_secret") == "super-secret-value"


def test_encrypt_decrypt_roundtrip_bytes(kms_provider):
    raw = b"\x00\x01\x02binary-bytes"
    blob = enc.encrypt_value(raw, kms_provider, purpose="api_key")
    assert enc.decrypt_value(blob, kms_provider, purpose="api_key") == raw


def test_ciphertext_format_is_versioned_and_decodable(kms_provider):
    blob = enc.encrypt_value("hello", kms_provider, purpose="p")
    raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
    assert raw[:2] == enc.VERSION_PREFIX == b"v1"
    # 12 字节 nonce + 至少一个字节密文 + 16 字节 tag
    assert len(raw) >= 2 + 12 + 1 + 16


def test_each_encryption_is_random(kms_provider):
    b1 = enc.encrypt_value("same-plaintext", kms_provider, purpose="p")
    b2 = enc.encrypt_value("same-plaintext", kms_provider, purpose="p")
    assert b1 != b2
    assert enc.decrypt_text(b1, kms_provider, purpose="p") == enc.decrypt_text(b2, kms_provider, purpose="p")


def test_unicode_roundtrip(kms_provider):
    text = "口令：密码！🔒"
    blob = enc.encrypt_value(text, kms_provider, purpose="p")
    assert enc.decrypt_text(blob, kms_provider, purpose="p") == text


# ---------------------------------------------------------------------------
# 篡改检测（GCM 认证标签）
# ---------------------------------------------------------------------------


def test_tampered_ciphertext_is_detected(kms_provider):
    blob = enc.encrypt_value("attack-at-dawn", kms_provider, purpose="p")
    raw = bytearray(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
    raw[-1] ^= 0x01  # 翻转 tag 的一个 bit
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    with pytest.raises(enc.EncryptionError) as excinfo:
        enc.decrypt_value(tampered, kms_provider, purpose="p")
    assert "authentication failed" in str(excinfo.value)


def test_tampered_plaintext_is_detected(kms_provider):
    blob = enc.encrypt_value("attack-at-dawn", kms_provider, purpose="p")
    raw = bytearray(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
    # 翻转 nonce 之后的密文部分
    raw[20] ^= 0x01
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value(tampered, kms_provider, purpose="p")


def test_wrong_purpose_is_rejected(kms_provider):
    """AAD 绑定 purpose：同一密钥下跨字段复用密文必须失败。"""
    blob = enc.encrypt_value("reused-blob", kms_provider, purpose="api_key")
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value(blob, kms_provider, purpose="mfa_secret")


def test_wrong_key_is_rejected(kms_provider):
    blob = enc.encrypt_value("attack-at-dawn", kms_provider, purpose="p")
    other = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "another-master-key-1234567890"})
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value(blob, other, purpose="p")


# ---------------------------------------------------------------------------
# 输入防护
# ---------------------------------------------------------------------------


def test_rejects_empty_plaintext(kms_provider):
    with pytest.raises(enc.EncryptionError):
        enc.encrypt_value("", kms_provider, purpose="p")
    with pytest.raises(enc.EncryptionError):
        enc.encrypt_value(b"", kms_provider, purpose="p")


def test_rejects_oversized_plaintext(kms_provider):
    with pytest.raises(enc.EncryptionError) as excinfo:
        enc.encrypt_value("x" * (enc.MAX_PLAINTEXT_BYTES + 1), kms_provider, purpose="p")
    assert "too large" in str(excinfo.value)


def test_rejects_unsupported_plaintext_type(kms_provider):
    with pytest.raises(enc.EncryptionError):
        enc.encrypt_value(12345, kms_provider, purpose="p")  # type: ignore[arg-type]


def test_rejects_missing_purpose(kms_provider):
    with pytest.raises(enc.EncryptionError):
        enc.encrypt_value("secret", kms_provider, purpose="")  # type: ignore[arg-type]


def test_rejects_malformed_blob(kms_provider):
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value("not-a-ciphertext", kms_provider, purpose="p")
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value("", kms_provider, purpose="p")
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value(12345, kms_provider, purpose="p")  # type: ignore[arg-type]


def test_rejects_unknown_version(kms_provider):
    # 伪造一个 v2 前缀的密文
    raw = b"v2" + b"\x00" * 32
    fake = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(enc.EncryptionError) as excinfo:
        enc.decrypt_value(fake, kms_provider, purpose="p")
    assert "version" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 轮换与工具函数
# ---------------------------------------------------------------------------


def test_reencrypt_preserves_plaintext(kms_provider):
    blob = enc.encrypt_value("rotate-me", kms_provider, purpose="p")
    rotated = enc.reencrypt(blob, kms_provider, purpose="p")
    assert rotated != blob
    assert enc.decrypt_text(rotated, kms_provider, purpose="p") == "rotate-me"


def test_rotation_across_master_keys():
    old = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: MASTER_KEY.decode()})
    new = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "rotated-master-key-1234567890"})
    blob = enc.encrypt_value("migrate-me", old, purpose="p")
    # 旧密钥产出的密文无法用新密钥直接解密
    with pytest.raises(enc.EncryptionError):
        enc.decrypt_value(blob, new, purpose="p")
    plaintext = enc.decrypt_text(blob, old, purpose="p")
    reencrypted = enc.encrypt_value(plaintext, new, purpose="p")
    assert enc.decrypt_text(reencrypted, new, purpose="p") == "migrate-me"


def test_is_encrypted_blob(kms_provider):
    blob = enc.encrypt_value("hello", kms_provider, purpose="p")
    assert enc.is_encrypted_blob(blob)
    assert enc.is_encrypted_blob("not-a-blob") is False
    assert enc.is_encrypted_blob(None) is False
    assert enc.is_encrypted_blob(12345) is False


def test_decrypt_optional_is_lenient(kms_provider):
    assert enc.decrypt_optional(None, kms_provider, purpose="p") is None
    assert enc.decrypt_optional("", kms_provider, purpose="p") == ""
    assert enc.decrypt_optional("plain-value", kms_provider, purpose="p") == "plain-value"
    blob = enc.encrypt_value("real-secret", kms_provider, purpose="p")
    assert enc.decrypt_optional(blob, kms_provider, purpose="p") == "real-secret"


def test_ciphertext_is_base64url_safe(kms_provider):
    blob = enc.encrypt_value("special chars!@#$%^&*()", kms_provider, purpose="p")
    assert not any(ch in blob for ch in "+/=")


def test_static_kms_helper_roundtrip():
    static = enc._StaticKms(MASTER_KEY)
    blob = enc.encrypt_value("static-key", static, purpose="p")
    assert enc.decrypt_text(blob, static, purpose="p") == "static-key"
    assert len(static.get_master_key()) == len(MASTER_KEY)
