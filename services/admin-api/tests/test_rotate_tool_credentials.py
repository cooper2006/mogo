"""034-credential-encryption / T031：主密钥轮换脚本的单测.

覆盖 T031 的三条断言：
1. 旧密钥加密的样本经轮换后**新密钥可解密、且原文一致**；
2. 轮换后**旧密钥解密失败**（证明密文确实换了密钥）；
3. 未加密的明文在轮换中被顺带加密（与迁移脚本行为一致）；
另覆盖无旧密钥时的"同密钥重加密演练"退化路径。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "rotate_tool_credentials_key.py"
ADMIN_API = REPO_ROOT / "services" / "admin-api"

NEW_KEY = "unit-test-new-master-key-0123456789"
OLD_KEY = "unit-test-old-master-key-abcdefghij"

os.environ.setdefault("MOGO_KMS_MASTER_KEY", NEW_KEY)
os.environ.setdefault("MOGO_ALLOW_INSECURE_DEV_KEY", "1")

if str(ADMIN_API) not in sys.path:
    sys.path.insert(0, str(ADMIN_API))


def _load_script():
    spec = importlib.util.spec_from_file_location("rotate_tool_credentials_key", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


rotation = _load_script()
from app.security.encryption import EncryptionError, decrypt_text, encrypt_value  # noqa: E402
from app.security.kms import MASTER_KEY_ENV, EnvVarKmsProvider  # noqa: E402
from app.security.tool_credentials import CREDENTIAL_PURPOSE  # noqa: E402


def _kms(secret: str) -> EnvVarKmsProvider:
    return EnvVarKmsProvider(env={MASTER_KEY_ENV: secret})


def test_rotate_reencrypts_from_old_key_to_new_key() -> None:
    old_kms, new_kms = _kms(OLD_KEY), _kms(NEW_KEY)
    legacy = encrypt_value("sk-live-abc", old_kms, purpose=CREDENTIAL_PURPOSE)

    rotated = rotation._rotate_value(legacy, old_kms, new_kms)

    assert rotated != legacy
    assert decrypt_text(rotated, new_kms, purpose=CREDENTIAL_PURPOSE) == "sk-live-abc"
    with pytest.raises(EncryptionError):
        decrypt_text(rotated, old_kms, purpose=CREDENTIAL_PURPOSE)


def test_rotate_encrypts_plaintext_with_new_key() -> None:
    new_kms = _kms(NEW_KEY)
    rotated = rotation._rotate_value("plain-token", None, new_kms)
    assert decrypt_text(rotated, new_kms, purpose=CREDENTIAL_PURPOSE) == "plain-token"


def test_rotate_without_old_key_degrades_to_same_key_drill() -> None:
    new_kms = _kms(NEW_KEY)
    original = encrypt_value("sk-live-abc", new_kms, purpose=CREDENTIAL_PURPOSE)

    rotated = rotation._rotate_value(original, None, new_kms)

    assert decrypt_text(rotated, new_kms, purpose=CREDENTIAL_PURPOSE) == "sk-live-abc"


def test_old_kms_returns_none_when_env_missing(monkeypatch: Any) -> None:
    monkeypatch.delenv(rotation.OLD_KEY_ENV, raising=False)
    assert rotation._old_kms() is None

    monkeypatch.setenv(rotation.OLD_KEY_ENV, OLD_KEY)
    provider = rotation._old_kms()
    assert provider is not None
