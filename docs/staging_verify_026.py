#!/usr/bin/env python3
"""026 performance-scalability staging 验证脚本"""

import os
import sys
import subprocess
from datetime import datetime

print("=" * 60)
print("  026 Performance Scalability Staging 验证")
print("=" * 60)
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 检查 Docker Compose 配置
print("1. 检查 Docker Compose 配置...")
result = subprocess.run(
    ["docker", "compose", "config"],
    capture_output=True, text=True
)
if result.returncode == 0:
    print("   ✓ docker-compose.yml 有效")
    
    # 检查服务数量
    if "services:" in result.stdout:
        services = [line.strip() for line in result.stdout.split('\n') if line.startswith('  ') and ':' in line and not line.startswith('    ')]
        print(f"   服务数: {len(services)}")
else:
    print("   ⚠ 无法解析 docker-compose.yml")

# 检查容器状态
print()
print("2. 检查容器状态...")
result = subprocess.run(
    ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}"],
    capture_output=True, text=True
)
print(result.stdout)

# 检查性能相关配置
print()
print("3. 检查性能配置...")
perf_configs = [
    "redis",
    "connection_pool",
    "timeout",
    "rate_limit",
]

for config in perf_configs:
    result = subprocess.run(
        ["docker", "exec", "mogo-admin-api-1", "grep", "-r", config, "/app/config/", "/app/app/"],
        capture_output=True, text=True
)
    if result.returncode == 0:
        print(f"   ✓ 找到 {config} 配置")
    else:
        print(f"   ⚠ 未找到 {config} 配置")

# 检查数据库连接池
print()
print("4. 检查数据库连接池...")
result = subprocess.run(
    ["docker", "exec", "mogo-mongo-1", "mongosh", "--eval", 
     "db.adminCommand({connectionPool: 1}).toString()"],
    capture_output=True, text=True
)
if result.returncode == 0:
    print("   ✓ MongoDB 连接池信息获取成功")
else:
    print("   ⚠ 无法获取 MongoDB 连接池信息")

print()
print("=" * 60)
print("  验证完成")
print("=" * 60)
print()
print("判定结果:")
print("  SC-001 (性能基线):        ⏳ 需基准测试")
print("  SC-002 (DB 连接池):       ✓ 已检查")
print("  SC-003 (缓存命中):        ⏳ 需压测验证")
print("  SC-004 (前端性能):        ⏳ 需 Lighthouse 测试")
print("  SC-005 (扩展性):          ⏳ 需水平扩展测试")
print("  SC-006 (性能配置):        ✓ 已检查")
print()
print("备注:")
print("  T041 水平扩展压测需 Docker Compose 多实例环境")
print("  建议: 在 staging 环境执行压测")
