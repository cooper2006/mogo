"""工具凭证主密钥轮换脚本（Feature 034 / T029）。

用于演练并执行 ``external_tools`` 集合凭证密文的主密钥轮换：

- 旧密钥来自环境变量 ``MOGO_KMS_MASTER_KEY_OLD``（**可选**）；
- 新密钥来自标准 ``MOGO_KMS_MASTER_KEY``（或文件/dev key，与运行环境一致）。
- 若未设置 ``MOGO_KMS_MASTER_KEY_OLD``，本脚本退化为「重加密演练」：
  用当前新密钥把密文解一遍再加密一遍，验证 reencrypt 链路可用，密文不变。

幂等性：已轮换（新密钥可解密）的密文会重加密一次并保持不变；明文（尚未
走 026 迁移）会被顺带加密。脚本不打印任何凭证明文。

用法：
    python scripts/rotate_tool_credentials_key.py --dry-run
    python scripts/rotate_tool_credentials_key.py --apply
    python scripts/rotate_tool_credentials_key.py --verify
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

from app.security.encryption import (  # noqa: E402
    decrypt_value,
    encrypt_value,
    is_encrypted_blob,
)
from app.security.kms import (  # noqa: E402
    MASTER_KEY_ENV,
    EnvVarKmsProvider,
)
from app.security.tool_credentials import (  # noqa: E402
    CREDENTIAL_PURPOSE,
    credential_keys,
    iter_credential_key_paths,
)

COLLECTION = "external_tools"
OLD_KEY_ENV = "MOGO_KMS_MASTER_KEY_OLD"


def _get_mongo() -> Any:
    from motor.motor_asyncio import AsyncIOMotorClient

    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("MOGO_DB_NAME") or "mogo"
    return AsyncIOMotorClient(uri)[db_name]


def _old_kms() -> EnvVarKmsProvider | None:
    secret = os.environ.get(OLD_KEY_ENV, "").strip()
    if not secret:
        return None
    return EnvVarKmsProvider(env={MASTER_KEY_ENV: secret})


def _rotate_value(value: str, old_kms: EnvVarKmsProvider | None, new_kms: EnvVarKmsProvider) -> str:
    if is_encrypted_blob(value):
        if old_kms is None:
            # 无旧密钥：退化为同密钥重加密演练（密钥未轮换）。
            plain = decrypt_value(value, new_kms, purpose=CREDENTIAL_PURPOSE)
            return encrypt_value(plain, new_kms, purpose=CREDENTIAL_PURPOSE)
        plain = decrypt_value(value, old_kms, purpose=CREDENTIAL_PURPOSE)
        return encrypt_value(plain, new_kms, purpose=CREDENTIAL_PURPOSE)
    # 尚未加密的明文：顺带用新密钥加密（与 026 迁移一致）。
    return encrypt_value(value, new_kms, purpose=CREDENTIAL_PURPOSE)


async def _docs_with_credentials(db: Any, keys: frozenset[str]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    async for doc in db[COLLECTION].find({"config": {"$type": "object"}}):
        config = doc.get("config")
        if not isinstance(config, dict):
            continue
        if any(
            isinstance(value, str) and value.strip()
            for _, value in iter_credential_key_paths(config, keys=keys)
        ):
            docs.append(doc)
    return docs


async def run_rotate(dry_run: bool) -> dict[str, Any]:
    keys = credential_keys()
    new_kms = EnvVarKmsProvider()
    old_kms = _old_kms()
    db = _get_mongo()
    docs = await _docs_with_credentials(db, keys)
    report: dict[str, Any] = {
        "collection": COLLECTION,
        "documents": len(docs),
        "rotated": 0,
        "errors": [],
        "old_key_present": old_kms is not None,
    }
    if dry_run:
        return report
    for doc in docs:
        config = doc.get("config") or {}
        new_config = dict(config)
        try:
            for path, value in iter_credential_key_paths(config, keys=keys):
                if not isinstance(value, str) or not value.strip():
                    continue
                rotated = _rotate_value(value, old_kms, new_kms)
                if len(path) == 1:
                    new_config[path[0]] = rotated
                else:
                    headers = new_config.get("headers")
                    if isinstance(headers, dict):
                        headers[path[1]] = rotated
            result = await db[COLLECTION].update_one(
                {"_id": doc["_id"]},
                {"$set": {"config": new_config}},
            )
            report["rotated"] += int(result.modified_count)
        except Exception as exc:  # noqa: BLE001  单个文档失败不中断整轮
            report["errors"].append({"_id": str(doc.get("_id")), "error": str(exc)})
    return report


async def run_verify(new_kms: EnvVarKmsProvider) -> dict[str, Any]:
    """复核：所有密文必须能用新密钥解密回非空明文。"""
    keys = credential_keys()
    db = _get_mongo()
    report: dict[str, Any] = {"collection": COLLECTION, "checked": 0, "unreadable": []}
    async for doc in db[COLLECTION].find({"config": {"$type": "object"}}):
        config = doc.get("config")
        if not isinstance(config, dict):
            continue
        for path, value in iter_credential_key_paths(config, keys=keys):
            if not is_encrypted_blob(value):
                continue
            report["checked"] += 1
            try:
                plain = decrypt_value(value, new_kms, purpose=CREDENTIAL_PURPOSE)
                if not str(plain).strip():
                    report["unreadable"].append(str(doc.get("_id")))
            except Exception:  # noqa: BLE001
                report["unreadable"].append(str(doc.get("_id")))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="工具凭证主密钥轮换（Feature 034）。")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只统计，不写库。")
    group.add_argument("--apply", action="store_true", help="实际轮换。")
    group.add_argument("--verify", action="store_true", help="复核新密钥可解密所有密文。")
    args = parser.parse_args()

    if args.verify:
        new_kms = EnvVarKmsProvider()
        report = asyncio.run(run_verify(new_kms))
        print(f"校验密文数={report['checked']} 不可读={len(report['unreadable'])}")
        for doc_id in report["unreadable"][:20]:
            print(f"  不可读: {doc_id}")
        return

    report = asyncio.run(run_rotate(dry_run=args.dry_run))
    print(
        f"集合={report['collection']} 含凭证文档={report['documents']} "
        f"旧密钥存在={report['old_key_present']} 已轮换={report['rotated']}"
    )
    for err in report["errors"][:20]:
        print(f"  错误: {err}")
    if args.dry_run:
        print("(dry-run) 未写库。确认后用 --apply 执行，再 --verify 复核。")


if __name__ == "__main__":
    main()