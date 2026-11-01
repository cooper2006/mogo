#!/usr/bin/env python3
"""SC-006: 运行安全相关测试（最终版）"""

import os
import sys
import subprocess
import re

# 设置路径
os.environ["MOGO_ALLOW_INSECURE_DEV_KEY"] = "1"
os.environ["MOGO_KMS_MASTER_KEY"] = os.popen("openssl rand -hex 32").read().strip()
os.environ["MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["MOGO_DB_NAME"] = "mogo_test_sc006"

print("=" * 60)
print("  SC-006: 运行安全测试套件")
print("=" * 60)
print()

# 运行特定的安全测试（从正确目录运行）
test_files = [
    "/tmp/admin-api-tests/test_drill_credential_scripts.py",
    "/tmp/admin-api-tests/test_migrate_tool_credentials.py",
]

total_passed = 0
total_failed = 0
total_errors = 0

for test_file in test_files:
    if os.path.exists(test_file):
        print(f"运行: {os.path.basename(test_file)}...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd="/tmp",
            env={**os.environ, "PYTHONPATH": "/tmp/mogo-admin-api:/tmp/scripts"}
        )
        # 统计结果
        match = re.search(r'(\d+) passed', result.stdout)
        if match:
            total_passed += int(match.group(1))
        match = re.search(r'(\d+) failed', result.stdout)
        if match:
            total_failed += int(match.group(1))
        match = re.search(r'(\d+) error', result.stdout)
        if match:
            total_errors += int(match.group(1))
        print(result.stdout[-300:] if len(result.stdout) > 300 else result.stdout)
        print()
    else:
        print(f"文件不存在: {test_file}")

print("=" * 60)
print(f"  总计: {total_passed} passed, {total_failed} failed, {total_errors} errors")
if total_failed == 0 and total_errors == 0 and total_passed > 0:
    print("  ✓ SC-006 通过: 测试全绿")
else:
    print("  ⏳ SC-006 待验证: 有测试失败或错误")
print("=" * 60)
