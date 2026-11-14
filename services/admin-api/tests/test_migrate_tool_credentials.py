"""034-credential-encryption / T027：存量迁移脚本的单测（fake collection）.

覆盖 FR-009 的五条契约：
1. 明文行被加密写回（密文可解密还原原文）；
2. 已加密行跳过且密文字节不变（幂等）；
3. 空值 / 非字符串凭证键跳过；
4. 中途失败行保持原状（不写回）+ 报告记录错误；
5. 二次运行迁移数为 0（幂等可证）+ 失败时退出码非零。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "migrate_tool_credentials_encryption.py"
ADMIN_API = REPO_ROOT / "services" / "admin-api"

# 加密需要可用的主密钥（022 EnvVarKmsProvider 语义）：优先显式密钥，否则 dev 密钥。
os.environ.setdefault("MOGO_KMS_MASTER_KEY", "unit-test-master-key-0123456789abcdef")
os.environ.setdefault("MOGO_ALLOW_INSECURE_DEV_KEY", "1")

if str(ADMIN_API) not in sys.path:
    sys.path.insert(0, str(ADMIN_API))


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_tool_credentials_encryption", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


migration = _load_script()
from app.security.encryption import decrypt_optional, encrypt_value, is_encrypted_blob  # noqa: E402
from app.security.kms import EnvVarKmsProvider  # noqa: E402
from app.security.tool_credentials import credential_keys  # noqa: E402


class _UpdateResult:
    def __init__(self, modified: int) -> None:
        self.modified_count = modified


class _FakeCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.updates: list[str] = []

    def _match(self, row: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            if isinstance(expected, dict) and "$type" in expected:
                if not isinstance(row.get(key), dict):
                    return False
                continue
            if row.get(key) != expected:
                return False
        return True

    def find(self, query: dict[str, Any] | None = None):
        rows = [row for row in self.rows if self._match(row, query or {})]

        class _Cursor:
            def __aiter__(self_inner):
                async def _gen():
                    for row in rows:
                        yield row

                return _gen()

        return _Cursor()

    async def count_documents(self, query: dict[str, Any] | None = None) -> int:
        return len([row for row in self.rows if self._match(row, query or {})])

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]):
        for row in self.rows:
            if self._match(row, query):
                row.update(update.get("$set") or {})
                self.updates.append(str(row.get("_id")))
                return _UpdateResult(1)
        return _UpdateResult(0)


class _FakeDB:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._collection = _FakeCollection(rows)

    def __getitem__(self, _name: str) -> _FakeCollection:
        return self._collection


def _plain_row(_id: str = "t1") -> dict[str, Any]:
    return {
        "_id": _id,
        "tenant_id": "t1",
        "type": "http",
        "config": {"endpoint": "https://example.test", "authType": "bearer", "authToken": "sk-live-abc"},
    }


def _run(monkeypatch, db, *, dry_run: bool) -> dict[str, Any]:
    monkeypatch.setattr(migration, "_get_mongo", lambda: db)
    return asyncio.run(migration.run_migration(dry_run=dry_run))


def test_scan_config_detects_plaintext_and_encrypted(monkeypatch) -> None:
    kms = EnvVarKmsProvider()
    keys = credential_keys(env={})
    ciphertext = encrypt_value("sk-live-abc", kms, purpose="external_tool_credential")

    rows, has_plaintext = migration._scan_config({"authToken": "sk-live-abc"}, keys)
    assert has_plaintext is True
    assert rows and rows[0][0] == "authToken"

    rows2, has_plaintext2 = migration._scan_config({"authToken": ciphertext}, keys)
    assert has_plaintext2 is False
    assert rows2 and rows2[0][1] == migration.ENCRYPTION_MARKER


def test_scan_config_skips_empty_and_non_string(monkeypatch) -> None:
    keys = credential_keys(env={})
    _, has_plaintext = migration._scan_config({"authToken": "", "apiKey": 12345}, keys)
    assert has_plaintext is False


def test_scan_config_handles_nested_headers() -> None:
    keys = credential_keys(env={})
    rows, has_plaintext = migration._scan_config({"headers": {"authToken": "plain-headers-token"}}, keys)
    assert has_plaintext is True
    assert rows[0][0] == "headers.authToken"


def test_dry_run_writes_nothing(monkeypatch) -> None:
    db = _FakeDB([_plain_row()])
    report = _run(monkeypatch, db, dry_run=True)
    assert report["pending"] == 1
    assert report["updated"] == 0
    assert db._collection.updates == []
    assert db._collection.rows[0]["config"]["authToken"] == "sk-live-abc"


def test_apply_encrypts_and_roundtrips(monkeypatch) -> None:
    db = _FakeDB([_plain_row()])
    report = _run(monkeypatch, db, dry_run=False)
    assert report["updated"] == 1
    assert report["errors"] == []

    stored = db._collection.rows[0]["config"]
    kms = EnvVarKmsProvider()
    assert stored["endpoint"] == "https://example.test"  # 非凭证字段保持明文
    assert is_encrypted_blob(stored["authToken"])  # <= b64url(b"v1" + nonce + ct||tag)
    assert decrypt_optional(stored["authToken"], kms, purpose="external_tool_credential") == "sk-live-abc"


def test_second_run_is_idempotent(monkeypatch) -> None:
    db = _FakeDB([_plain_row()])
    _run(monkeypatch, db, dry_run=False)
    first_ciphertext = db._collection.rows[0]["config"]["authToken"]

    second = _run(monkeypatch, db, dry_run=False)
    assert second["pending"] == 0
    assert second["updated"] == 0
    assert db._collection.rows[0]["config"]["authToken"] == first_ciphertext  # 密文字节不变


def test_failure_row_stays_original(monkeypatch) -> None:
    db = _FakeDB([_plain_row()])

    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("kms unavailable")

    monkeypatch.setattr(migration, "encrypt_credentials", _boom)
    report = _run(monkeypatch, db, dry_run=False)
    assert report["updated"] == 0
    assert report["errors"] and report["errors"][0]["_id"] == "t1"
    assert db._collection.rows[0]["config"]["authToken"] == "sk-live-abc"  # 保持原状
    assert db._collection.updates == []


@pytest.mark.parametrize("remaining", [0, 1])
def test_verify_reports_remaining_plaintext(monkeypatch, remaining: int) -> None:
    db = _FakeDB([_plain_row()] if remaining else [])
    monkeypatch.setattr(migration, "_get_mongo", lambda: db)
    report = asyncio.run(migration.run_verify())
    assert report["remaining_plaintext"] == remaining
