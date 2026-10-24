"""034-credential-encryption 的本地可执行演练（T034/T035 的本地段，staging 段仍需人工）。

范围（诚实降级，见 spec.md 判定口径补充 R-5/R-8/R-9/R-15 与 ``docs/credential-key-rotation-drill.md``）：
  - 本文件用**独立的临时库名**在本地 mongod（127.0.0.1:27017）上建明文样本，然后通过 subprocess
    真实调用 ``scripts/migrate_tool_credentials_encryption.py`` 与 ``scripts/rotate_tool_credentials_key.py``，
    覆盖「dry-run → apply → verify → 二次幂等 → 无明文对账 → 轮换后可解密」；结束 drop 临时库。
  - **不做**（需 staging / mongodump）：真实备份回滚（SC-003 的 mongodump 段）、Agent 侧注入回放（SC-002）、
    多副本轮换。这些由 034 的 T033/T035 staging 段覆盖。
  - 依赖：本地 mongod 在 127.0.0.1:27017 开放（未运行则本文件 pytest.skip）。

跑法：
    cd services/admin-api && ASKAI_ADMIN_MONGODB_URI=mongodb://127.0.0.1:27017 \
        python3 -m pytest tests/test_drill_credential_scripts.py -o addopts="" -q -p no:cacheprovider
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATE = REPO_ROOT / "scripts" / "migrate_tool_credentials_encryption.py"
ROTATE = REPO_ROOT / "scripts" / "rotate_tool_credentials_key.py"

PLAINTEXT_CONFIG: dict[str, Any] = {
    "url": "https://example.invalid/api",
    "method": "GET",
    "authType": "bearer",
    "authToken": "plain-token-abc",
    "headers": {"X-Custom": "plain-secret-xyz"},
    "nested": {"apiKey": "plain-key-001"},
}

MIGRATE_ENV = {
    **os.environ,
    "MONGODB_URI": "mongodb://127.0.0.1:27017",
    "MONGO_URL": "",
    "MOGO_DB_NAME": "mogo_drill_034",  # 独立临时库，隔离并行会话数据
    "MOGO_ALLOW_INSECURE_DEV_KEY": "1",
}


def _run(script: Path, *args: str, env: dict[str, str] | None = None,
         db_name: str = "mogo_drill_034") -> subprocess.CompletedProcess[str]:
    # db_name 由调用方传入，保证脚本连的库与测试插入/断言的是同一个独立临时库。
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        env={**MIGRATE_ENV, "MOGO_DB_NAME": db_name, **(env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def db_name() -> str:
    return f"mogo_drill_034_{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def client(db_name: str) -> AsyncIOMotorClient:
    return AsyncIOMotorClient("mongodb://127.0.0.1:27017")


async def _insert_plaintext(client: AsyncIOMotorClient, db_name: str) -> None:
    db = client[db_name]
    await db.external_tools.insert_many(
        [
            {"_id": "drill-1", "tenant_id": "drill-t1", "name": "Drill One",
             "type": "http", "scope": "organization", "status": "active", "config": PLAINTEXT_CONFIG},
            {"_id": "drill-2", "tenant_id": "drill-t1", "name": "Drill Two",
             "type": "http", "scope": "organization", "status": "active",
             "config": {"url": "https://example.invalid/api", "method": "POST",
                        "authType": "api_key", "apiKeyHeader": "X-API-Key",
                        "authToken": "plain-key-002", "headers": {}}},
        ]
    )


async def _plaintext_paths(client: AsyncIOMotorClient, db_name: str) -> list[str]:
    """列出仍含明文的凭证字段路径（只扫 ``credential_keys()`` 白名单：顶层 + headers 内同名键）。

    注意：非凭证键（如 ``headers.X-Custom``、``nested.*``）按 FR-012 不在加密范围，
    ``nested`` 子字典也本就不被 ``iter_credential_key_paths`` 识别，故不计为缺口。
    """
    from app.security.tool_credentials import credential_keys, is_encrypted_blob, iter_credential_key_paths

    paths: list[str] = []
    keys = credential_keys()
    for row in await client[db_name].external_tools.find({}).to_list(length=100):
        config = row.get("config") or {}
        for path, value in iter_credential_key_paths(config, keys=keys):
            if isinstance(value, str) and value.strip() and not is_encrypted_blob(value):
                paths.append(f"{row['_id']}.{'|'.join(path)}<plaintext>")
    return paths


@pytest.mark.asyncio
async def test_drill_migrate_dry_run_apply_verify_idempotent(client: AsyncIOMotorClient, db_name: str) -> None:
    # 先确认 mongod 可达，否则整份演练跳过（staging 段仍需人工）。
    try:
        await client.admin.command("ping")
    except Exception as exc:  # pragma: no cover - 环境缺失
        pytest.skip(f"本地 mongod 不可达：{exc}")
    await _insert_plaintext(client, db_name)

    # 1) dry-run：只统计、不写库
    dry = _run(MIGRATE, "--dry-run", db_name=db_name)
    assert dry.returncode == 0, dry.stderr[-800:]
    after_dry = await _plaintext_paths(client, db_name)
    assert len(after_dry) >= 2, f"dry-run 后仍应保留明文样本，但仅发现 {after_dry}"

    # 2) apply：真实加密
    app = _run(MIGRATE, "--apply", db_name=db_name)
    assert app.returncode == 0, app.stderr[-800:]
    after_apply = await _plaintext_paths(client, db_name)
    assert after_apply == [], f"apply 后仍存在明文路径：{after_apply}"

    # 3) verify：复核
    ver = _run(MIGRATE, "--verify", db_name=db_name)
    assert ver.returncode == 0, ver.stderr[-800:]

    # 4) 二次幂等：再 apply 仍 exit 0，且仍无明文
    again = _run(MIGRATE, "--apply", db_name=db_name)
    assert again.returncode == 0, again.stderr[-800:]
    assert await _plaintext_paths(client, db_name) == []

    # 5) 轮换演练：无 OLD 密钥 → 重加密演练，verify 通过
    rot = _run(ROTATE, "--apply", db_name=db_name)
    assert rot.returncode == 0, rot.stderr[-800:]
    rot_ver = _run(ROTATE, "--verify", db_name=db_name)
    assert rot_ver.returncode == 0, rot_ver.stderr[-800:]
    assert await _plaintext_paths(client, db_name) == []

    # 清理
    await client.drop_database(db_name)