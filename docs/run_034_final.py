#!/usr/bin/env python3
"""034 credential-encryption 完整验证脚本"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 设置环境变量
os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["MOGO_DB_NAME"] = "mogo_staging_034_verify"
os.environ["MOGO_ALLOW_INSECURE_DEV_KEY"] = "1"
os.environ["MOGO_KMS_MASTER_KEY"] = os.popen("openssl rand -hex 16").read().strip()
os.environ["MOGO_KMS_MASTER_KEY_OLD"] = os.popen("openssl rand -hex 16").read().strip()

# 添加 admin-api 到路径
sys.path.insert(0, "/tmp/mogo-admin-api")

print("=" * 60)
print("  034 Credential Encryption 完整验证")
print("=" * 60)
print(f"数据库: {os.environ['MOGO_DB_NAME']}")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

from pymongo import MongoClient
client = MongoClient(os.environ["MONGODB_URI"])
mongo_db = client[os.environ["MOGO_DB_NAME"]]

# 1. 清理
print("1. 清理测试数据库...")
client.drop_database(os.environ["MOGO_DB_NAME"])
print("   ✓ 清理完成")

# 2. 插入明文凭证
print()
print("2. 插入测试凭证数据...")
test_data = [
    {"name": "test-tool-1", "config": {"api_key": "sk-test-key-1-secret", "api_secret": "secret-test-1"}, "tenant_id": "t1"},
    {"name": "test-tool-2", "config": {"oauth_token": "oauth-test-token-value"}, "tenant_id": "t1"},
    {"name": "test-tool-3", "config": {"password": "plain-text-password-123"}, "tenant_id": "t2"},
]
mongo_db.external_tools.insert_many(test_data)
count = mongo_db.external_tools.count_documents({})
print(f"   ✓ 插入 {count} 条测试数据")

# 3. 执行迁移
print()
print("3. 执行迁移脚本...")
result = subprocess.run(
    [sys.executable, "/tmp/migrate_tool_credentials_encryption.py", "--dry-run"],
    capture_output=True, text=True,
    env={**os.environ}
)
print("   dry-run:", result.stdout.strip())

result = subprocess.run(
    [sys.executable, "/tmp/migrate_tool_credentials_encryption.py", "--apply"],
    capture_output=True, text=True,
    env={**os.environ}
)
print("   apply:", result.stdout.strip())
if result.stderr:
    print("   STDERR:", result.stderr[:200])

# 4. 验证无明文 (SC-001)
print()
print("4. 验证 DB 无明文 (SC-001)...")
docs = list(mongo_db.external_tools.find({}, {"config": 1, "name": 1}))
plain_keywords = ["sk-test-key-1-secret", "oauth-test-token-value", "plain-text-password-123"]
plain_count = 0
for d in docs:
    config_str = str(d.get("config", {}))
    for kw in plain_keywords:
        if kw in config_str:
            plain_count += 1
            print(f"   ✗ 发现明文: {d.get('name')}")
            break

if plain_count == 0:
    print("   ✓ SC-001 通过: DB 无明文残留")
else:
    print(f"   ✗ SC-001 失败: {plain_count} 处明文残留")
    # 打印实际数据供调试
    for d in docs:
        print(f"   数据: {d['name']} = {d.get('config')}")

# 5. 轮换演练
print()
print("5. 轮换演练...")
result = subprocess.run(
    [sys.executable, "/tmp/rotate_tool_credentials_key.py", "--dry-run"],
    capture_output=True, text=True,
    env={**os.environ}
)
print("   dry-run:", result.stdout.strip())

result = subprocess.run(
    [sys.executable, "/tmp/rotate_tool_credentials_key.py", "--apply"],
    capture_output=True, text=True,
    env={**os.environ}
)
print("   apply:", result.stdout.strip())

result = subprocess.run(
    [sys.executable, "/tmp/rotate_tool_credentials_key.py", "--verify"],
    capture_output=True, text=True,
    env={**os.environ}
)
print("   verify:", result.stdout.strip())

# 6. 清理
print()
print("6. 清理测试数据库...")
client.drop_database(os.environ["MOGO_DB_NAME"])
print("   ✓ 清理完成")

print()
print("=" * 60)
print("  验证完成")
print("=" * 60)
