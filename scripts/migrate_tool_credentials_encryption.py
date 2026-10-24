"""一次性加密存量工具凭证（Feature 034 / T026）。

背景：在 034-credential-encryption 上线前，``external_tools.config`` 的凭证字段
（authToken / token / apiKey / secret / password / accessToken / refreshToken，
含 ``config.headers`` 内同名键）以明文落库。本脚本把这些存量明文凭证一次性
改写为 AES-GCM 密文，与新增写入路径保持一致（purpose=``external_tool_credential``）。

幂等性：已加密的字段（``is_encrypted_blob``）原样保留，脚本可重复执行；
执行前请先确认 ``MOGO_KMS_MASTER_KEY``（或 ``MOGO_KMS_MASTER_KEY_FILE`` /
dev 密钥）已就位，并完成一次 mongodump 备份。

用法：
    python scripts/migrate_tool_credentials_encryption.py --dry-run   # 只统计
    python scripts/migrate_tool_credentials_encryption.py --apply     # 实际加密
    python scripts/migrate_tool_credentials_encryption.py --verify    # 复核

注意：本脚本**不会**打印任何凭证明文，只输出字段路径与是否加密的标记。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "admin-api"))

from app.security.encryption import is_encrypted_blob  # noqa: E402
from app.security.tool_credentials import (  # noqa: E402
    credential_keys,
    encrypt_credentials,
    iter_credential_key_paths,
)

COLLECTION = "external_tools"
ENCRYPTION_MARKER = "密文"  # 仅用于展示，避免回显明文


def _get_mongo() -> Any:
    # 延迟导入，便于无 DB 环境检查脚本结构。
    from motor.motor_asyncio import AsyncIOMotorClient

    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("MOGO_DB_NAME") or "mogo"
    return AsyncIOMotorClient(uri)[db_name]


def _scan_config(config: dict[str, Any], keys: frozenset[str]) -> tuple[list[tuple[str, str]], bool]:
    """返回 (待加密字段路径列表, 是否还有明文凭证)。"""
    pending: list[tuple[str, str]] = []
    has_plaintext = False
    for path, value in iter_credential_key_paths(config, keys=keys):
        if not isinstance(value, str) or not value.strip():
            continue
        if is_encrypted_blob(value):
            pending.append((".".join(path), ENCRYPTION_MARKER))
        else:
            pending.append((".".join(path), "明文待加密"))
            has_plaintext = True
    return pending, has_plaintext


async def _pending_docs(db: Any, keys: frozenset[str]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    async for doc in db[COLLECTION].find({"config": {"$type": "object"}}):
        config = doc.get("config")
        if not isinstance(config, dict):
            continue
        _, has_plaintext = _scan_config(config, keys)
        if has_plaintext:
            docs.append(doc)
    return docs


async def run_migration(dry_run: bool) -> dict[str, Any]:
    keys = credential_keys()
    db = _get_mongo()
    docs = await _pending_docs(db, keys)
    report: dict[str, Any] = {"collection": COLLECTION, "scanned": 0, "pending": len(docs), "updated": 0, "errors": []}
    report["scanned"] = await db[COLLECTION].count_documents({"config": {"$type": "object"}})
    if dry_run:
        report["updated"] = 0
        for doc in docs[:5]:
            paths, _ = _scan_config(doc.get("config") or {}, keys)
            report.setdefault("samples", []).append({"_id": str(doc.get("_id")), "fields": paths})
        return report
    for doc in docs:
        doc_id = str(doc.get("_id"))
        try:
            new_config = encrypt_credentials(doc.get("config") or {}, keys=keys)
        except Exception as exc:  # noqa: BLE001  KmsConfigError / EncryptionError 等
            report["errors"].append({"_id": doc_id, "error": str(exc)})
            continue
        result = await db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {"config": new_config}})
        report["updated"] += int(result.modified_count)
    return report


async def run_verify() -> dict[str, Any]:
    keys = credential_keys()
    db = _get_mongo()
    report: dict[str, Any] = {"collection": COLLECTION, "remaining_plaintext": 0, "checked": 0, "errors": []}
    async for doc in db[COLLECTION].find({"config": {"$type": "object"}}):
        config = doc.get("config")
        if not isinstance(config, dict):
            continue
        paths, has_plaintext = _scan_config(config, keys)
        report["checked"] += 1
        if has_plaintext:
            report["remaining_plaintext"] += 1
            report["errors"].append({"_id": str(doc.get("_id")), "fields": [p for p, _ in paths]})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="一次性加密存量工具凭证（Feature 034）。")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只统计待加密文档，不写库。")
    group.add_argument("--apply", action="store_true", help="实际加密并写回。")
    group.add_argument("--verify", action="store_true", help="复核剩余明文凭证。")
    args = parser.parse_args()

    if args.verify:
        report = asyncio.run(run_verify())
        print(f"检查文档数={report['checked']} 剩余明文={report['remaining_plaintext']}")
        for err in report["errors"][:20]:
            print(f"  仍有明文: {err}")
        # FR-009：仍有明文（复核未通过）→ 非零退出码，便于 CI/运维判定。
        if report["remaining_plaintext"]:
            sys.exit(1)
        return

    report = asyncio.run(run_migration(dry_run=args.dry_run))
    print(f"集合={report['collection']} 扫描文档={report['scanned']} 待加密={report['pending']} 已更新={report['updated']}")
    for sample in report.get("samples", []):
        print(f"  样例 {sample['_id']}: {sample['fields']}")
    for err in report["errors"][:20]:
        print(f"  错误: {err}")
    if args.dry_run:
        print("(dry-run) 未写库。确认后请用 --apply 执行。")
        return
    # FR-009：存在失败行（保持原状、不写回）→ 非零退出码。
    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()