#!/usr/bin/env python3
"""040 T019: 可观测接线验证 - log_trace 和 token_usage_logs 含 tier 字段"""

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

print("=" * 60)
print("  040 T019: 可观测接线验证")
print("=" * 60)
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

from pymongo import MongoClient
client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)
client.admin.command('ping')
mongo_db = client[os.environ["MOGO_DB_NAME"]]

# 1. 检查 log_trace 是否有 tier 字段
print("1. 检查 log_trace 集合...")
log_trace_count = mongo_db.log_trace.count_documents({})
print(f"   log_trace 文档数: {log_trace_count}")

if log_trace_count > 0:
    # 检查是否有 tier 字段
    with_tier = mongo_db.log_trace.count_documents({"tier": {"$exists": True, "$ne": None}})
    print(f"   含 tier 字段: {with_tier}")
    
    if with_tier > 0:
        sample = mongo_db.log_trace.find_one({"tier": {"$exists": True}})
        print(f"   ✓ log_trace 含 tier 字段: {sample.get('tier')}")
    else:
        print("   ⚠ log_trace 无 tier 字段，需检查数据")
        # 查看样本
        sample = mongo_db.log_trace.find_one()
        if sample:
            print(f"   样本字段: {list(sample.keys())}")
else:
    print("   ⚠ log_trace 无数据，需触发 Agent 调用")

# 2. 检查 token_usage_logs 是否有 tier 字段
print()
print("2. 检查 token_usage_logs 集合...")
usage_count = mongo_db.token_usage_logs.count_documents({})
print(f"   token_usage_logs 文档数: {usage_count}")

if usage_count > 0:
    with_tier = mongo_db.token_usage_logs.count_documents({"tier": {"$exists": True, "$ne": None}})
    print(f"   含 tier 字段: {with_tier}")
    
    if with_tier > 0:
        sample = mongo_db.token_usage_logs.find_one({"tier": {"$exists": True}})
        print(f"   ✓ token_usage_logs 含 tier 字段: {sample.get('tier')}")
    else:
        print("   ⚠ token_usage_logs 无 tier 字段")
        sample = mongo_db.token_usage_logs.find_one()
        if sample:
            print(f"   样本字段: {list(sample.keys())}")
else:
    print("   ⚠ token_usage_logs 无数据")

# 3. 检查两集合关联
print()
print("3. 检查 log_trace 与 token_usage_logs 关联...")
# 尝试通过 request_id 关联
if usage_count > 0:
    sample_usage = mongo_db.token_usage_logs.find_one()
    request_id = sample_usage.get("request_id")
    if request_id:
        linked = mongo_db.log_trace.count_documents({"request_id": request_id})
        print(f"   request_id={request_id} 关联 log_trace: {linked} 条")
        if linked > 0:
            print("   ✓ 两集合可通过 request_id 关联")
    else:
        print("   ⚠ 无 request_id 字段，无法关联")
else:
    print("   ⚠ 无 token_usage_logs 数据，无法验证关联")

# 4. 检查 tier 值分布
print()
print("4. 检查 tier 值分布...")
if usage_count > 0:
    tier_dist = list(mongo_db.token_usage_logs.aggregate([
        {"$group": {"_id": "$tier", "count": {"$sum": 1}}}
    ]))
    print("   token_usage_logs tier 分布:")
    for d in tier_dist:
        print(f"     {d['_id']}: {d['count']} 次")
else:
    print("   ⚠ 无数据")

# 5. 结论
print()
print("=" * 60)
print("  验证结论")
print("=" * 60)

log_trace_ok = log_trace_count > 0 and with_tier > 0 if log_trace_count > 0 else False
usage_ok = usage_count > 0 and with_tier > 0 if usage_count > 0 else False

if log_trace_ok and usage_ok:
    print("  ✓ T019 通过: log_trace 和 token_usage_logs 均含 tier 字段")
elif log_trace_ok or usage_ok:
    print("  🟡 T019 部分通过: 仅一个集合含 tier 字段")
    print("  ⏳ 需触发真实 Agent 调用生成完整数据")
else:
    print("  ⏳ T019 待验证: 需真实 Agent 调用生成数据")
    print("  建议: 在 admin-web 触发一次对话，然后重新检查")
