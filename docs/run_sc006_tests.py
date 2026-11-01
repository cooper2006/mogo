#!/usr/bin/env python3
"""SC-006: 运行安全相关测试"""

import os
import sys
import subprocess
from pathlib import Path

# 设置路径
sys.path.insert(0, '/tmp/mogo-admin-api')
sys.path.insert(0, '/tmp/admin-api-tests')

os.environ["MOGO_ALLOW_INSECURE_DEV_KEY"] = "1"
os.environ["MOGO_KMS_MASTER_KEY"] = os.popen("openssl rand -hex 32").read().strip()
os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["MOGO_DB_NAME"] = "mogo_test_sc006"

print("=" * 60)
print("  SC-006: 运行安全测试套件")
print("=" * 60)
print()

# 运行特定的安全测试
test_files = [
    "/tmp/admin-api-tests/test_drill_credential_scripts.py",
    "/tmp/admin-api-tests/test_migrate_tool_credentials.py",
]

for test_file in test_files:
    if os.path.exists(test_file):
        print(f"运行: {os.path.basename(test_file)}...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "/tmp/mogo-admin-api:/tmp/admin-api-tests"}
        )
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr[:200])
        print()
    else:
        print(f"文件不存在: {test_file}")

print("=" * 60)
print("  测试完成")
print("=" * 60)
