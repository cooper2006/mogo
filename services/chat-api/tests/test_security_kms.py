"""FR-19 (QF-651–656) KMS 接口测试.

覆盖：HKDF 派生确定性/长度/独立性、环境变量实现的正常与 fail-closed 路径、
文件读取、开发用弱密钥开关、Vault 预留实现、密钥指纹不泄露原文。
"""

import pytest

from app.security import kms


# ---------------------------------------------------------------------------
# HKDF 派生
# ---------------------------------------------------------------------------


def test_hkdf_outputs_32_bytes_deterministically():
    k1 = kms.hkdf_sha256(b"master", info="purpose-a")
    k2 = kms.hkdf_sha256(b"master", info="purpose-a")
    assert k1 == k2
    assert len(k1) == kms.DATA_KEY_SIZE == 32


def test_hkdf_derives_different_keys_per_purpose():
    # 主密钥与数据密钥分离：不同 purpose → 不同数据密钥
    a = kms.derive_data_key(b"same-master-key-1234", purpose="mfa_secret")
    b = kms.derive_data_key(b"same-master-key-1234", purpose="api_key")
    assert a != b
    assert len(a) == len(b) == 32


def test_hkdf_derives_different_keys_per_master():
    a = kms.derive_data_key(b"master-one-12345", purpose="mfa_secret")
    b = kms.derive_data_key(b"master-two-12345", purpose="mfa_secret")
    assert a != b


def test_derive_data_key_rejects_empty_master_key():
    with pytest.raises(kms.KmsConfigError):
        kms.derive_data_key(b"", purpose="x")


def test_hkdf_rejects_bad_length():
    with pytest.raises(ValueError):
        kms.hkdf_sha256(b"ikm", length=0)
    with pytest.raises(ValueError):
        kms.hkdf_sha256(b"ikm", length=99999)


def test_fingerprint_is_stable_and_short():
    fp = kms.fingerprint(b"some-master-key")
    assert len(fp) == 8
    assert fp == kms.fingerprint(b"some-master-key")
    assert b"some-master-key" not in fp.encode()


# ---------------------------------------------------------------------------
# EnvVarKmsProvider：正常路径
# ---------------------------------------------------------------------------


def test_env_provider_returns_master_key():
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "a-very-long-master-key-1234"})
    assert provider.get_master_key() == b"a-very-long-master-key-1234"
    assert len(provider.data_key_for("mfa_secret")) == 32


def test_env_provider_strips_whitespace():
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "  key-with-space-1234  "})
    assert provider.get_master_key() == b"key-with-space-1234"


def test_env_provider_reads_from_file(tmp_path):
    key_file = tmp_path / "master.key"
    key_file.write_bytes(b"file-backed-master-key-1234")
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_FILE_ENV: str(key_file)})
    assert provider.get_master_key() == b"file-backed-master-key-1234"


def test_env_provider_prefers_file_over_env_var(tmp_path):
    key_file = tmp_path / "master.key"
    key_file.write_bytes(b"file-backed-master-key-1234")
    provider = kms.EnvVarKmsProvider(
        env={
            kms.MASTER_KEY_FILE_ENV: str(key_file),
            kms.MASTER_KEY_ENV: "env-backed-master-key-1234",
        }
    )
    assert provider.get_master_key() == b"file-backed-master-key-1234"


def test_env_provider_describe_hides_key_material():
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "a-very-long-master-key-1234"})
    desc = provider.describe()
    assert desc["configured"] is True
    assert desc["master_key_bytes"] == len(b"a-very-long-master-key-1234")
    assert desc["master_key_fingerprint"]
    assert "a-very-long-master-key-1234" not in repr(desc)


# ---------------------------------------------------------------------------
# EnvVarKmsProvider：fail-closed
# ---------------------------------------------------------------------------


def test_env_provider_fails_closed_when_unset():
    provider = kms.EnvVarKmsProvider(env={})
    with pytest.raises(kms.KmsConfigError) as excinfo:
        provider.get_master_key()
    assert kms.MASTER_KEY_ENV in str(excinfo.value)


def test_env_provider_rejects_short_master_key():
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "short"})
    with pytest.raises(kms.KmsConfigError) as excinfo:
        provider.get_master_key()
    assert "too short" in str(excinfo.value)


def test_env_provider_rejects_missing_file(tmp_path):
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_FILE_ENV: str(tmp_path / "nope.key")})
    with pytest.raises(kms.KmsConfigError):
        provider.get_master_key()


def test_env_provider_accepts_dev_key_only_when_flagged():
    provider = kms.EnvVarKmsProvider(env={kms.ALLOW_DEV_KEY_ENV: "1"})
    assert provider.get_master_key() == kms.DEV_MASTER_KEY


def test_env_provider_does_not_fallback_without_flag():
    # 未设置 MOGO_ALLOW_INSECURE_DEV_KEY 时，绝不允许回退到内置弱密钥
    provider = kms.EnvVarKmsProvider(env={})
    with pytest.raises(kms.KmsConfigError):
        provider.get_master_key()
    assert provider.describe()["configured"] is False


def test_env_provider_allows_dev_key_with_true_or_yes():
    for value in ("true", "TRUE", "yes", "1"):
        provider = kms.EnvVarKmsProvider(env={kms.ALLOW_DEV_KEY_ENV: value})
        assert provider.get_master_key() == kms.DEV_MASTER_KEY


def test_env_provider_min_length_is_configurable():
    provider = kms.EnvVarKmsProvider(
        env={kms.MASTER_KEY_ENV: "abcd"},
        config=kms.EnvVarKmsProviderConfig(min_master_key_bytes=4),
    )
    assert provider.get_master_key() == b"abcd"


def test_load_master_key_from_env_helper():
    assert kms.load_master_key_from_env({kms.MASTER_KEY_ENV: "helper-key-12345678"}) == b"helper-key-12345678"


# ---------------------------------------------------------------------------
# Vault 预留实现
# ---------------------------------------------------------------------------


def test_vault_provider_is_reserved_not_implemented():
    provider = kms.VaultKmsProvider(address="https://vault.internal", token="vault-token")
    assert provider.describe()["configured"] is True
    with pytest.raises(kms.KmsProviderUnavailable) as excinfo:
        provider.get_master_key()
    assert "reserved" in str(excinfo.value)


def test_vault_provider_describe_hides_token():
    provider = kms.VaultKmsProvider(token="vault-token")
    desc = provider.describe()
    assert desc["token_configured"] is True
    assert "vault-token" not in repr(desc)


def test_provider_selection_and_registry():
    assert kms.get_provider_name() == kms.KMS_PROVIDER_ENV
    assert kms.SUPPORTED_PROVIDERS == (kms.KMS_PROVIDER_ENV, kms.KMS_PROVIDER_VAULT)
    providers = list(kms.iter_providers())
    assert kms.EnvVarKmsProvider in providers
    assert kms.VaultKmsProvider in providers
    assert set(kms.describe_all_providers()["supported"]) == set(kms.SUPPORTED_PROVIDERS)


def test_data_key_for_uses_purpose_isolation():
    provider = kms.EnvVarKmsProvider(env={kms.MASTER_KEY_ENV: "provider-master-key-1234"})
    d1 = provider.data_key_for("mfa_secret")
    d2 = provider.data_key_for("mfa_secret")
    d3 = provider.data_key_for("api_key")
    assert d1 == d2  # 同一 purpose 稳定
    assert d1 != d3  # 不同 purpose 隔离
