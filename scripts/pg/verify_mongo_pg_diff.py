#!/usr/bin/env python3
"""R2 差分测试：同一批 Mongo 操作在 MongoDB 与 PanWeiDB 兼容层上跑，比对结果。

这是 R2 最可靠的验收方式——静态分析只能猜「该实现什么」，差分测试直接告诉你
「实现得对不对」。凡是两边结果不一致的，都说明兼容层有语义偏差。

前置条件：

* MongoDB 可达（`--mongo-uri`）。
  注意：`mogo_backend` 是 `internal` docker 网络，容器既无外网也发布不了端口；
  若要连栈内的 MongoDB，需先起一个 TCP 转发容器把端口映射到宿主机，参考
  `docs/mongo-to-panweidb-migration-plan.md` 第 8 节。
* PanWeiDB 可达（`--dsn`），且目标 schema 已存在。

用法::

    python scripts/pg/verify_mongo_pg_diff.py \\
        --mongo-uri "mongodb://127.0.0.1:27018" --mongo-db mogo_dev \\
        --dsn "host=127.0.0.1 port=5432 user=boncuser password=... dbname=bonc" \\
        --schema mogo_dev
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "admin-api"))

from pymongo import (  # noqa: E402
    DeleteMany,
    DeleteOne,
    InsertOne,
    MongoClient,
    ReplaceOne,
    UpdateMany,
    UpdateOne,
)

#: (标签, 集合, 管道)
PIPELINES = [
    ("group-count-by-field", "enterprise_tool_audit", [
        {"$match": {"event": {"$exists": True}}},
        {"$group": {"_id": "$event", "count": {"$sum": 1}}},
    ]),
    ("group-global-sum-ifnull", "token_usage_logs", [
        {"$match": {"status": {"$ne": "failed"}}},
        {"$group": {"_id": None, "tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}}}},
    ]),
    ("group-min-max-avg", "token_usage_logs", [
        {"$match": {}},
        {"$group": {"_id": "$model_name", "min_start": {"$min": "$start_time"},
                    "max_end": {"$max": "$end_time"}, "avg_tokens": {"$avg": "$total_tokens"},
                    "calls": {"$sum": 1}}},
    ]),
    ("group-first-last-after-sort", "token_usage_logs", [
        {"$match": {}},
        {"$sort": {"created_at": 1}},
        {"$group": {"_id": "$model_name", "first_stage": {"$first": "$stage"},
                    "last_stage": {"$last": "$stage"}, "first_intent": {"$first": "$intent"}}},
    ]),
    ("group-sort-limit", "enterprise_tool_audit", [
        {"$match": {}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]),
    ("group-count-stage", "enterprise_tool_audit", [
        {"$match": {}},
        {"$group": {"_id": "$user_id"}},
        {"$count": "count"},
    ]),
    ("group-push-addtoset", "enterprise_tool_audit", [
        {"$match": {}},
        {"$group": {"_id": "$tenant_id", "all_events": {"$push": "$event"},
                    "unique_events": {"$addToSet": "$event"}}},
    ]),
    ("group-cond-in-id-and-sum", "token_usage_logs", [
        {"$match": {}},
        {"$group": {"_id": {"$cond": [{"$eq": ["$status", "failed"]}, "failed", "ok"]},
                    "failed_count": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
                    "total": {"$sum": 1}}},
    ]),
    ("group-composite-id", "enterprise_tool_audit", [
        {"$match": {}},
        {"$group": {"_id": {"t": "$tenant_id", "u": "$user_id"}, "count": {"$sum": 1}}},
    ]),
    ("group-large-dataset", "kernel_event_inbox", [
        {"$match": {"tenant_id": {"$exists": True}}},
        {"$group": {"_id": "$tenant_id", "count": {"$sum": 1}, "max_cursor": {"$max": "$cursor"}}},
        {"$sort": {"count": -1}},
    ]),
]

#: $percentile 无法与 Mongo 6.0 对照（7.0+ 才有），单独验证
PERCENTILE_PIPELINE = ("token_usage_logs", [
    {"$match": {"end_time": {"$gt": 0}}},
    {"$project": {"duration_ms_percentiles": {"$percentile": {
        "input": {"$max": [0, {"$subtract": [
            {"$ifNull": ["$end_time", 0]}, {"$ifNull": ["$start_time", 0]}]}]},
        "p": [0.5, 0.95], "method": "approximate"}}}},
])


def _normalize(value):
    """规范化结果，便于比较（排序无关、类型宽容）。"""
    if isinstance(value, list):
        return sorted((_normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return str(value)


def _bulk_ops(prefix: str) -> list:
    return [
        InsertOne({"_id": f"{prefix}-1", "v": 1, "tags": ["a"]}),
        InsertOne({"_id": f"{prefix}-2", "v": 2, "tags": []}),
        UpdateOne({"_id": f"{prefix}-1"}, {"$set": {"v": 10}, "$push": {"tags": "b"}}),
        UpdateMany({"v": {"$gte": 2}}, {"$inc": {"v": 1}}),
        ReplaceOne({"_id": f"{prefix}-2"}, {"_id": f"{prefix}-2", "v": 99, "replaced": True}),
        DeleteOne({"_id": f"{prefix}-1"}),
        DeleteMany({"v": {"$lt": 0}}),
        UpdateOne({"_id": f"{prefix}-9"}, {"$set": {"v": 9}}, upsert=True),
    ]


async def _check_aggregation(mongo, pg) -> tuple[int, int]:
    print("[聚合管道差分]")
    ok = fail = 0
    for label, collection, pipeline in PIPELINES:
        expected = _normalize(list(mongo[collection].aggregate(pipeline)))
        try:
            actual = _normalize(await pg[collection].aggregate(pipeline).to_list(length=None))
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {label}: 执行失败 -> {str(exc).splitlines()[0][:100]}")
            fail += 1
            continue
        if actual == expected:
            ok += 1
            print(f"  ✅ {label}  ({len(expected)} 组)")
        else:
            fail += 1
            print(f"  ❌ {label}  期望 {len(expected)} 组 / 实际 {len(actual)} 组")
            for i in range(max(len(expected), len(actual))):
                e = expected[i] if i < len(expected) else "<缺>"
                a = actual[i] if i < len(actual) else "<缺>"
                if e != a:
                    print(f"       第 {i} 组不同：")
                    print(f"         mongo   : {json.dumps(e, ensure_ascii=False, default=str)[:200]}")
                    print(f"         panweidb: {json.dumps(a, ensure_ascii=False, default=str)[:200]}")
                    break

    # $percentile：Mongo 6.0 不支持，无法对照
    print("\n[$percentile（Mongo 6.0 不支持，单独验证）]")
    collection, pipeline = PERCENTILE_PIPELINE
    try:
        rows = await pg[collection].aggregate(pipeline).to_list(length=None)
        values = rows[0].get("duration_ms_percentiles") if rows else None
        if isinstance(values, list) and len(values) == 2:
            p50, p95 = float(values[0]), float(values[1])
            print(f"  {'✅' if 0 <= p50 <= p95 else '❌'} 返回 [p50={p50}, p95={p95}]，"
                  f"p50<=p95 且非负: {0 <= p50 <= p95}")
            ok, fail = (ok + 1, fail) if 0 <= p50 <= p95 else (ok, fail + 1)
        else:
            print(f"  ❌ 返回形状不对: {values!r}")
            fail += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 执行失败: {str(exc).splitlines()[0][:110]}")
        fail += 1
    return ok, fail


async def _check_bulk_write(mongo, pg, pool, schema) -> tuple[int, int]:
    print("\n[bulk_write 差分]")
    coll = "bulk_write_probe"
    mongo[coll].drop()
    # DROP 必须带 schema 限定：连接的 search_path 是 '"$user",public'（不含目标
    # schema），裸标识符会解析到不存在的同名表，IF EXISTS 静默 no-op，上一轮残留
    # 数据就会污染本轮计数——2026-10-14 回归时 bulk_write 的 matched/modified/
    # upserted 因此误报失败（实际计数与 MongoDB 一致）。见 WORK_LOG 2026-10-14。
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f'DROP TABLE IF EXISTS {schema}."{coll}"')
    ok = fail = 0

    def check(label, actual, expected):
        nonlocal ok, fail
        if actual == expected:
            ok += 1
            print(f"  ✅ {label}: {actual}")
        else:
            fail += 1
            print(f"  ❌ {label}\n     期望={expected!r}\n     实际={actual!r}")

    expected = mongo[coll].bulk_write(_bulk_ops("m"), ordered=True)
    actual = await pg[coll].bulk_write(_bulk_ops("p"), ordered=True)
    for field in ("inserted_count", "matched_count", "modified_count",
                  "deleted_count", "upserted_count"):
        check(field, getattr(actual, field), getattr(expected, field))

    m_docs = sorted(({k: v for k, v in d.items() if k != "_id"}
                     for d in mongo[coll].find({})), key=lambda d: str(d))
    p_docs = sorted(({k: v for k, v in d.items() if k != "_id"}
                     for d in await pg[coll].find({}).to_list(length=None)),
                    key=lambda d: str(d))
    check("落库文档集合一致", p_docs, m_docs)
    check("文档条数", len(p_docs), len(m_docs))

    empty = await pg[coll].bulk_write([], ordered=True)
    check("空请求列表不报错且全 0", (empty.inserted_count, empty.deleted_count), (0, 0))

    mongo[coll].drop()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f'DROP TABLE IF EXISTS {schema}."{coll}"')
    return ok, fail


async def main() -> int:
    parser = argparse.ArgumentParser(description="R2 差分测试")
    parser.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27018")
    parser.add_argument("--mongo-db", default="mogo_dev")
    parser.add_argument("--dsn", required=True, help="libpq 连接串")
    parser.add_argument("--schema", default="mogo_dev")
    args = parser.parse_args()

    mongo = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10000)[args.mongo_db]

    import psycopg_pool
    from app.core.pg_compat import PgDatabase

    pool = psycopg_pool.AsyncConnectionPool(args.dsn, min_size=1, max_size=4, open=False)
    await pool.open(wait=True)
    pg = PgDatabase(pool, args.schema)

    try:
        ok1, fail1 = await _check_aggregation(mongo, pg)
        ok2, fail2 = await _check_bulk_write(mongo, pg, pool, args.schema)
    finally:
        await pool.close()

    total_ok, total_fail = ok1 + ok2, fail1 + fail2
    print(f"\n{'='*60}\n通过 {total_ok} / 失败 {total_fail}\n{'='*60}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
