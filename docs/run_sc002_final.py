#!/usr/bin/env python3
"""SC-002: Agent 注入验证（最终版）"""

import os
import sys
import subprocess
from datetime import datetime

# 获取 MongoDB IP
mongo_ip = subprocess.run(
    ["docker", "inspect", "mogo-mongo-1", "--format", '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'],
    capture_output=True, text=True
).stdout.strip()

os.environ["MONGODB_URI"] = f"mongodb://{mongo_ip}:27017"
os.environ["MOGO_DB_NAME"] = "mogo"
os.environ["MOGO_ALLOW_INSECURE_DEV_KEY"] = "1"
os.environ["MOGO_KMS_MASTER_KEY"] = os.popen("openssl rand -hex 16").read().strip()

sys.path.insert(0, "/tmp/mogo-admin-api")

print("=" * 60)
print("  SC-002: Agent 注入验证")
print("=" * 60)
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

from pymongo import MongoClient
from app.security.encryption import encrypt_value, decrypt_value, is_encrypted_blob
from app.security.kms import EnvVarKmsProvider

client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)
client.admin.command('ping')
mongo_db = client[os.environ["MOGO_DB_NAME"]]

# 1. 清理
print("1. 清理测试数据...")
mongo_db.external_tools.delete_many({"name": {"$regex": "^test-sc002-"}})
print("   ✓ 清理完成")

# 2. 插入明文凭证
print()
print("2. 插入明文凭证...")
mongo_db.external_tools.insert_one({
    "name": "test-sc002-tool-1",
    "config": {"token": "sk-sc002-inject-test-token"},
    "tenant_id": "t1"
})
print("   ✓ 插入明文凭证")

# 3. 加密凭证
print()
print("3. 加密凭证...")
kms = EnvVarKmsProvider()
doc = mongo_db.external_tools.find_one({"name": "test-sc002-tool-1"})
config = doc["config"]
config["token"] = encrypt_value(config["token"], kms, purpose="external_tool_credential")
mongo_db.external_tools.update_one({"_id": doc["_id"]}, {"$set": {"config": config}})
print("   ✓ 加密完成")

# 4. 验证 DB 无明文
print()
print("4. 验证 DB 无明文...")
doc = mongo_db.external_tools.find_one({"name": "test-sc002-tool-1"})
config_str = str(doc.get("config", {}))
if "sk-sc002-inject-test-token" in config_str:
    print("   ✗ SC-002 失败: DB 仍有明文")
    sys.exit(1)
else:
    print("   ✓ DB 无明文")

# 5. 验证可解密
print()
print("5. 验证凭证可解密...")
try:
    decrypted = decrypt_value(doc["config"]["token"], kms, purpose="external_tool_credential")
    # 处理 bytes 返回值
    if isinstance(decrypted, bytes):
        decrypted = decrypted.decode('utf-8')
    if decrypted == "sk-sc002-inject-test-token":
        print("   ✓ 解密成功，凭证可正常注入")
    else:
        print(f"   ✗ 解密值不匹配: {decrypted}")
        sys.exit(1)
except Exception as e:
    print(f"   ✗ 解密失败: {e}")
    sys.exit(1)

# 6. 模拟 Agent 注入场景
print()
print("6. 模拟 Agent 工具调用...")
print("   场景: Agent 调用 test-sc002-tool-1")
print("   预期: 凭证被解密并注入，日志无明文")

# 验证加密格式
print(f"   加密后格式: {str(doc['config']['token'])[:50]}...")
print(f"   是加密 blob: {is_encrypted_blob(doc['config']['token'])}")

print("   ✓ 模拟完成（需真实 Agent 调用验证日志）")

# 7. 清理
print()
print("7. 清理测试数据...")
mongo_db.external_tools.delete_many({"name": {"$regex": "^test-sc002-"}})
print("   ✓ 清理完成")

print()
print("=" * 60)
print("  SC-002 验证完成")
print("=" * 60)
print()
print("判定结果:")
print("  ✓ DB 无明文残留")
print("  ✓ 凭证可正常解密")
print("  ⏳ 需真实 Agent 调用验证日志")
print()
print("下一步:")
print("  1. 在 admin-web 创建使用 test-sc002-tool-1 的 Agent")
print("  2. 触发一次工具调用")
print("  3. 检查 chat-api 日志:")
print("     docker logs mogo-chat-api-1 --tail 100 | grep -i 'token|credential'")
