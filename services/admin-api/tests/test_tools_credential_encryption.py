"""Feature 034 - 工具凭证加密接线测试.

覆盖：
- ``app.security.tool_credentials`` 纯函数（加密/宽容解密/掩码/保留合并）；
- ``app.api.routes.tools`` 的 ``_normalize_payload`` / ``_serialize`` 接线行为；
- 迁移脚本 ``scripts/migrate_tool_credentials_encryption.py`` 的幂等与 dry-run；
- 轮换脚本 ``scripts/rotate_tool_credentials_key.py`` 的演练与复核。

测试不依赖真实 Mongo（conftest 已 stub motor），纯函数 + monkeypatch 环境变量。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes.tools import _normalize_payload, _serialize
from app.security import kms
from app.security.encryption import is_encrypted_blob
from app.security.tool_credentials import (
    MASK,
    decrypt_credentials,
    encrypt_credentials,
    merge_credential_preserve,
    redact_credentials,
    reset_tool_credential_kms_cache,
)

MASTER_KEY = b"unit-test-master-key-1234567890"
ENV_KEY = kms.MASTER_KEY_ENV
ENV_KEY_DEV = kms.ALLOW_DEV_KEY_ENV

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _kms_env(monkeypatch: pytest.MonkeyPatch):
    """默认注入有效主密钥并清空进程缓存。"""
    monkeypatch.setenv(ENV_KEY, MASTER_KEY.decode())
    reset_tool_credential_kms_cache()
    yield
    reset_tool_credential_kms_cache()


# ---------------------------------------------------------------------------
# encrypt_credentials
# ---------------------------------------------------------------------------


def test_encrypt_credentials_encrypts_only_credential_keys():
    config = {"authType": "bearer", "authToken": "sk-abc", "endpoint": "https://x"}
    out = encrypt_credentials(config)
    assert is_encrypted_blob(out["authToken"])
    assert out["endpoint"] == "https://x"
    assert out["authType"] == "bearer"
    assert "sk-abc" not in repr(out)


def test_encrypt_credentials_covers_default_key_set():
    keys = ["authToken", "token", "apiKey", "secret", "password", "accessToken", "refreshToken"]
    config = {k: f"value-{k}" for k in keys}
    out = encrypt_credentials(config)
    for k in keys:
        assert is_encrypted_blob(out[k]), k


def test_encrypt_credentials_encrypts_headers_credential_keys():
    config = {"headers": {"apiKey": "live-key", "secret": "live-secret", "X-Key": "k"}}
    out = encrypt_credentials(config)
    assert is_encrypted_blob(out["headers"]["apiKey"])
    assert is_encrypted_blob(out["headers"]["secret"])
    assert out["headers"]["X-Key"] == "k"


def test_encrypt_credentials_idempotent_on_ciphertext():
    config = {"authToken": "secret-token"}
    once = encrypt_credentials(config)
    twice = encrypt_credentials(once)
    assert once["authToken"] == twice["authToken"]


def test_encrypt_credentials_skips_empty_and_non_string():
    config = {"authToken": "", "apiKey": None, "secret": 123, "endpoint": "https://x"}
    out = encrypt_credentials(config)
    assert out["authToken"] == ""
    assert out["apiKey"] is None
    assert out["secret"] == 123
    assert not is_encrypted_blob(str(out["secret"]))


def test_encrypt_credentials_no_credential_does_not_touch_kms(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    reset_tool_credential_kms_cache()
    # 无凭证字段时不应触发 KMS（authType=none 的工具在密钥缺失时不报错）。
    config = {"authType": "none", "url": "https://example.com"}
    assert encrypt_credentials(config) == config


def test_encrypt_credentials_missing_key_raises_kms_config_error(monkeypatch: pytest.MonkeyPatch):
    # 同时清掉开发回退开关：EnvVarKmsProvider 在 MOGO_ALLOW_INSECURE_DEV_KEY 置真时
    # 会用内置弱密钥而不是抛 KmsConfigError。tests/test_migrate_tool_credentials.py 与
    # tests/test_rotate_tool_credentials.py 在模块导入期 os.environ.setdefault 该变量，
    # 泄漏到整个会话——本用例必须自己把它清掉，否则"缺密钥必须报错"的断言失效。
    monkeypatch.delenv(ENV_KEY, raising=False)
    monkeypatch.delenv(ENV_KEY_DEV, raising=False)
    reset_tool_credential_kms_cache()
    from app.security.kms import KmsConfigError

    with pytest.raises(KmsConfigError):
        encrypt_credentials({"authToken": "sk-abc"})


# ---------------------------------------------------------------------------
# decrypt_credentials
# ---------------------------------------------------------------------------


def test_decrypt_credentials_roundtrip():
    config = {"authToken": "sk-roundtrip", "endpoint": "https://x"}
    enc = encrypt_credentials(config)
    dec = decrypt_credentials(enc)
    assert dec["authToken"] == "sk-roundtrip"
    assert dec["endpoint"] == "https://x"


def test_decrypt_credentials_tolerant_to_plaintext():
    # 双跑期：明文与密文共存时，宽容解密应把明文原样返回。
    config = {"authToken": "sk-plain", "secret": "sk-plain-2"}
    out = decrypt_credentials(config)
    assert out["authToken"] == "sk-plain"
    assert out["secret"] == "sk-plain-2"


# ---------------------------------------------------------------------------
# redact_credentials
# ---------------------------------------------------------------------------


def test_redact_credentials_masks_set_keys():
    config = {"authToken": "sk-secret-very-long", "endpoint": "https://x"}
    out = redact_credentials(config)
    assert out["authToken"] == MASK
    assert out["endpoint"] == "https://x"


def test_redact_credentials_does_not_inject_mask_for_empty():
    config = {"authToken": "", "endpoint": "https://x"}
    out = redact_credentials(config)
    assert "authToken" not in out
    assert out["endpoint"] == "https://x"


# ---------------------------------------------------------------------------
# merge_credential_preserve
# ---------------------------------------------------------------------------


def test_merge_inherits_missing_credential_from_existing():
    existing = {"authToken": "v1|existingciphertext"}
    incoming = {"endpoint": "https://y"}
    out = merge_credential_preserve(incoming, existing)
    assert out["authToken"] == "v1|existingciphertext"


def test_merge_overrides_when_new_value_provided():
    existing = {"authToken": "v1|old"}
    incoming = {"authToken": "sk-new"}
    out = merge_credential_preserve(incoming, existing)
    assert out["authToken"] == "sk-new"


def test_merge_treats_mask_as_not_reprovided():
    existing = {"authToken": "v1|oldcipher"}
    incoming = {"authToken": MASK}
    out = merge_credential_preserve(incoming, existing)
    assert out["authToken"] == "v1|oldcipher"


def test_merge_headers_credential_keys():
    existing = {"headers": {"apiKey": "v1|headercipher", "X-Key": "v1|keep"}}
    incoming = {"headers": {"secret": "new-secret"}}
    out = merge_credential_preserve(incoming, existing)
    assert out["headers"]["apiKey"] == "v1|headercipher"
    assert out["headers"]["secret"] == "new-secret"


# ---------------------------------------------------------------------------
# routes.tools 接线
# ---------------------------------------------------------------------------


def test_normalize_payload_encrypts_config():
    payload = {"name": "t", "type": "http", "config": {"authToken": "sk-x", "url": "https://x"}}
    patch = _normalize_payload(payload)
    assert is_encrypted_blob(patch["config"]["authToken"])
    assert patch["config"]["url"] == "https://x"


def test_normalize_payload_partial_without_config_skips_encryption():
    payload = {"name": "t2"}
    patch = _normalize_payload(payload, partial=True)
    assert "config" not in patch


def test_normalize_payload_merges_existing_credentials():
    payload = {"name": "t3", "type": "http", "config": {"url": "https://y"}}
    patch = _normalize_payload(
        payload,
        existing_config={"authToken": "v1|existingcipher"},
    )
    assert is_encrypted_blob(patch["config"]["authToken"])
    assert patch["config"]["url"] == "https://y"


def test_normalize_payload_missing_key_returns_503(monkeypatch: pytest.MonkeyPatch):
    # 同 test_encrypt_credentials_missing_key_raises_kms_config_error：必须清掉
    # 开发回退开关，否则缺密钥时走内置弱密钥而不是返回 503。
    monkeypatch.delenv(ENV_KEY, raising=False)
    monkeypatch.delenv(ENV_KEY_DEV, raising=False)
    reset_tool_credential_kms_cache()
    payload = {"name": "t", "type": "http", "config": {"authToken": "sk-x"}}
    with pytest.raises(HTTPException) as exc_info:
        _normalize_payload(payload)
    assert exc_info.value.status_code == 503
    assert "加密不可用" in exc_info.value.detail


def test_serialize_redacts_config():
    doc: dict[str, Any] = {"_id": "d1", "name": "n", "type": "http", "config": {"authToken": "sk-secret", "url": "https://x"}}
    out = _serialize(doc)
    assert out["config"]["authToken"] == MASK
    assert out["config"]["url"] == "https://x"


def test_serialize_does_not_expose_plaintext():
    doc: dict[str, Any] = {"_id": "d1", "name": "n", "type": "http", "config": {"authToken": "sk-secret", "url": "https://x"}}
    out = _serialize(doc)
    assert "sk-secret" not in repr(out)


# ---------------------------------------------------------------------------
# 迁移脚本
# ---------------------------------------------------------------------------


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self.updated: list[dict[str, Any]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        return len(self.docs)

    async def find(self, query: dict[str, Any]):
        for doc in self.docs:
            if isinstance(doc.get("config"), dict):
                yield doc

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]):
        self.updated.append(update)
        doc_id = query["_id"]
        for doc in self.docs:
            if doc["_id"] == doc_id:
                doc.update(update["$set"])
        return type("R", (), {"modified_count": 1})()


class _FakeDb:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.coll = _FakeCollection(docs)

    def __getitem__(self, name: str) -> _FakeCollection:
        assert name == "external_tools"
        return self.coll


@pytest.fixture()
def migration_script(monkeypatch: pytest.MonkeyPatch):
    module = _load_script("migrate_tool_credentials_encryption")
    fake_db = _FakeDb([])
    monkeypatch.setattr(module, "_get_mongo", lambda: fake_db)
    return module, fake_db


def test_migration_dry_run_reports_without_writing(migration_script):
    module, fake_db = migration_script
    fake_db.coll.docs = [
        {"_id": "a", "config": {"authToken": "sk-plain", "url": "https://x"}},
        {"_id": "b", "config": {"url": "https://y"}},
    ]
    report = asyncio.run(module.run_migration(dry_run=True))
    assert report["pending"] == 1
    assert report["updated"] == 0
    assert fake_db.coll.updated == []


def test_migration_apply_encrypts_and_is_idempotent(migration_script):
    module, fake_db = migration_script
    fake_db.coll.docs = [
        {"_id": "a", "config": {"authToken": "sk-plain", "url": "https://x"}},
        {"_id": "b", "config": {"url": "https://y"}},
    ]
    first = asyncio.run(module.run_migration(dry_run=False))
    assert first["updated"] == 1
    assert is_encrypted_blob(fake_db.coll.docs[0]["config"]["authToken"])
    assert fake_db.coll.docs[1]["config"]["url"] == "https://y"
    second = asyncio.run(module.run_migration(dry_run=False))
    assert second["updated"] == 0
    assert second["pending"] == 0


# ---------------------------------------------------------------------------
# 轮换脚本
# ---------------------------------------------------------------------------


@pytest.fixture()
def rotation_script(monkeypatch: pytest.MonkeyPatch):
    module = _load_script("rotate_tool_credentials_key")
    fake_db = _FakeDb([])
    monkeypatch.setattr(module, "_get_mongo", lambda: fake_db)
    monkeypatch.delenv(module.OLD_KEY_ENV, raising=False)
    return module, fake_db


def test_rotation_drill_same_key_is_idempotent(rotation_script):
    module, fake_db = rotation_script
    encrypted = encrypt_credentials({"authToken": "sk-secret"})
    fake_db.coll.docs = [{"_id": "a", "config": encrypted}]
    report = asyncio.run(module.run_rotate(dry_run=False))
    assert report["rotated"] == 1
    # 演练路径（未设置旧密钥）解密后可还原原明文（密文 nonce 随机，字节不同）。
    restored = decrypt_credentials(fake_db.coll.docs[0]["config"])
    assert restored["authToken"] == "sk-secret"


def test_rotation_verify_reports_unreadable(rotation_script):
    module, fake_db = rotation_script
    # 用另一个密钥加密的密文，在当前密钥下不可读。
    other_kms = kms.EnvVarKmsProvider(env={ENV_KEY: "different-master-key-1234567890"})
    from app.security.encryption import encrypt_value
    from app.security.tool_credentials import CREDENTIAL_PURPOSE

    foreign = encrypt_value("secret", other_kms, purpose=CREDENTIAL_PURPOSE)
    fake_db.coll.docs = [{"_id": "a", "config": {"authToken": foreign}}]
    report = asyncio.run(module.run_verify(kms.EnvVarKmsProvider(env={ENV_KEY: MASTER_KEY.decode()})))
    assert report["checked"] == 1
    assert len(report["unreadable"]) == 1


def test_rotation_dry_run_does_not_write(rotation_script):
    module, fake_db = rotation_script
    encrypted = encrypt_credentials({"authToken": "sk-secret"})
    fake_db.coll.docs = [{"_id": "a", "config": encrypted}]
    report = asyncio.run(module.run_rotate(dry_run=True))
    assert report["rotated"] == 0
    assert fake_db.coll.updated == []