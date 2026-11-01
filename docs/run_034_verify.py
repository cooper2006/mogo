#!/usr/bin/env python3
"""034 credential-encryption 本地验证脚本"""

import os
import sys
import subprocess
from pathlib import Path

os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["MOGO_DB_NAME"] = "mogo_staging_034_verify"
os.environ["MOGO_ALLOW_INSECURE_DEV_KEY"] = "1"
os.environ["MOGO_KMS_MASTER_KEY"] = os.popen("openssl rand -hex 16").read().strip()
os.environ["MOGO_KMS_MASTER_KEY_OLD"] = os.popen("openssl rand -hex 16").read().strip()

# 使用 workspace 中的脚本路径
PROJECT_DIR = Path("/tmp/workspace")
SCRIPTS_DIR = PROJECT_DIR / "scripts"

# 先复制脚本到临时目录
import shutil
shutil.copy("/Users/cooper/Documents/deepseek-harness/default-workspace/../layerfs-work/layerfs-full/.agents/skills/layerfs-js-sdk/SKILL.md", "/dev/null")  # 占位

print("=== 034 Credential Encryption 本地验证 ===")
print(f"数据库: {os.environ['MOGO_DB_NAME']}")
print()

from pymongo import MongoClient
client = MongoClient(os.environ["MONGODB_URI"])
mongo_db = client[os.environ["MOGO_DB_NAME"]]

# 清理
print("1. 清理测试数据库...")
client.drop_database(os.environ["MOGO_DB_NAME"])

# 插入明文凭证
print("2. 插入测试凭证数据...")
mongo_db.external_tools.insert_many([
    {"name": "test-tool-1", "config": {"api_key": "sk-test-key-1-secret", "api_secret": "secret-test-1"}, "tenant_id": "t1"},
    {"name": "test-tool-2", "config": {"oauth_token": "oauth-test-token"}, "tenant_id": "t1"},
    {"name": "test-tool-3", "config": {"password": "plain-password"}, "tenant_id": "t2"},
])
count = mongo_db.external_tools.count_documents({})
print(f"   插入 {count} 条测试数据")

# 执行迁移 - 使用 LayerFS 项目中的脚本
print()
print("3. 执行迁移 (--dry-run)...")
# 从 workspace 读取脚本
lf_scripts_dir = Path("/tmp/layerscripts")
lf_scripts_dir.mkdir(exist_ok=True)

# 复制脚本
import subprocess as sp
sp.run(["cp", "-r", "/Users/cooper/.layerfs/projects/mogo/scripts", str(lf_scripts_dir)], check=False)

result = sp.run([sys.executable, str(lf_scripts_dir / "migrate_tool_credentials_encryption.py"), "--dry-run"],
               capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:300])

print("3. 执行迁移 (--apply)...")
result = sp.run([sys.executable, str(lf_scripts_dir / "migrate_tool_credentials_encryption.py"), "--apply"],
               capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:300])

# 验证无明文
print()
print("4. 验证 DB 无明文 (SC-001)...")
docs = list(mongo_db.external_tools.find({}, {"config": 1, "name": 1}))
plain_count = 0
for d in docs:
    config_str = str(d.get("config", {}))
    if any(s in config_str for s in ["sk-test-key-1-secret", "oauth-test-token", "plain-password"]):
        plain_count += 1
        print(f"   ✗ 发现明文: {d.get('name')}")

if plain_count == 0:
    print("   ✓ SC-001 通过: DB 无明文")
else:
    print(f"   ✗ SC-001 失败: {plain_count} 条明文残留")
    print("   (脚本路径问题，需使用 LayerFS workspace 执行)")

# 清理
print()
print("5. 清理...")
client.drop_database(os.environ["MOGO_DB_NAME"])

print()
print("=== 034 验证说明 ===")
print("本地验证因脚本路径问题未完成。")
print("请使用 LayerFS workspace 执行以下命令:")
print("  layerfs workspace exec <ws> 'cd services/admin-api && python scripts/migrate_tool_credentials_encryption.py --apply'")
