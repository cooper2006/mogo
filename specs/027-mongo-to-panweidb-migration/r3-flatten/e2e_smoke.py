#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""R3 兼容层端到端冒烟：把 pg_compat 生成的 SQL 拿到 openGauss 真库执行。

做法：fake pool 捕获 PgCollection 各方法的真实 (sql, params)，参数安全内联成
字面量，输出为可直接 gsql -f 的 SQL 文件。只读优先；写操作用已存在的数据行
保证幂等（insert 走 ON CONFLICT DO NOTHING，update 的 $set 用原值）。
会写库（UPDATE doc/updated_at 与列同步），禁止对生产库执行。

用法（在仓库任意目录）：
    python3 e2e_smoke.py > e2e_smoke.sql     # 生成（同时打印）
    docker cp e2e_smoke.sql panweidb:/tmp/
    docker exec panweidb sh -c "su - omm -c 'export PATH=/database/panweidb/soft/bin:\$PATH; \
      export LD_LIBRARY_PATH=/database/panweidb/soft/lib:\$LD_LIBRARY_PATH; gsql -d mogo_dev -U omm -f /tmp/e2e_smoke.sql'"

常量（表/行/库）可用环境变量覆盖：SMOKE_SCHEMA / SMOKE_SESSION_ID / SMOKE_USER_ID。
产物末尾会 DROP 冒烟索引，不碰数据之外的状态。
"""
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "services" / "admin-api"))

from app.core.pg_compat import PgCollection  # noqa: E402

SCHEMA = os.environ.get("SMOKE_SCHEMA", "mogo_dev")
SESSION_ID = os.environ.get("SMOKE_SESSION_ID", "6aba655f2c893150f01bfda8")   # chat_sessions 已存在行
USER_ID = os.environ.get("SMOKE_USER_ID", "6ab9dd0382f60252a4a40aa6")         # end_users 已存在行


def lit(value):
    """参数 → SQL 字面量（与 _inline_placeholders 同风格：单引号转义）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return "'" + text.replace("'", "''") + "'"


class CapturePool:
    """记录 SQL 的假连接池。"""

    def __init__(self, rows=None):
        self.log = []
        self._rows = rows or []

    class _Cur:
        def __init__(self, outer):
            self._o = outer
            self.rowcount = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, sql, params=None):
            self._o.log.append((sql, list(params or [])))

        async def fetchall(self):
            return self._o._rows

        async def fetchone(self):
            return self._o._rows[0] if self._o._rows else None

    class _Conn:
        def __init__(self, outer):
            self._o = outer

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def cursor(self):
            return CapturePool._Cur(self._o)

    def connection(self):
        return CapturePool._Conn(self)


def inline(sql, params):
    out = sql
    for p in params:
        out = out.replace("%s", lit(p), 1)
    return out


def main():
    captured = []

    # ---- 1. find_one：映射键筛选 + SELECT 带列 ----
    pool = CapturePool()
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_find():
        await coll.find_one({"user_id": USER_ID})

    import asyncio
    asyncio.run(cap_find())
    captured.append(pool.log[-1])

    # ---- 2. $in / 范围筛选 ----
    pool = CapturePool()
    coll = PgCollection(pool, "knowledge_documents", SCHEMA)

    async def cap_count():
        await coll.count_documents({"status": {"$in": ["ready", "failed"]}, "file_size": {"$gte": 0}})

    asyncio.run(cap_count())
    captured.append(pool.log[-1])

    # ---- 3. insert_one 双写（已存在 id → ON CONFLICT DO NOTHING，不落数据）----
    pool = CapturePool()
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_insert():
        await coll.insert_one({"_id": SESSION_ID, "tenant_id": "t", "user_id": USER_ID, "title": "冒烟"})

    asyncio.run(cap_insert())
    captured.append(pool.log[-1])

    # ---- 4. update_one $set（原值幂等）+ CTE 列同步 ----
    pool = CapturePool(rows=[(1,)])
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_update():
        await coll.update_one(
            {"_id": SESSION_ID},
            {"$set": {
                "user_id": USER_ID,
                "title": "生成一份结构化分诊报告",   # 原值，幂等
                "participant_ids": None,             # 原值为 NULL，验 JSON null 防护
            }},
        )

    asyncio.run(cap_update())
    captured.append(pool.log[-1])

    # ---- 5. create_index 走真实列（字符串形式，与业务代码一致）----
    pool = CapturePool()
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_index():
        await coll.create_index("user_id", name="smoke_chat_sessions_user_id")
        await coll.create_index(
            "status", unique=True, name="smoke_uq_chat_sessions_status",
            partialFilterExpression={"deleted_at": None},
        )

    asyncio.run(cap_index())
    captured.extend(pool.log)

    # ---- 6. ORDER BY 路由（find_one + cursor sort）----
    pool = CapturePool()
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_sort():
        await coll.find_one({"user_id": USER_ID}, sort=[("user_id", -1)])
        cursor = coll.find({}).sort("user_id", 1).sort("custom_dynamic", -1).limit(3)
        await cursor.to_list()

    asyncio.run(cap_sort())
    captured.append(pool.log[0])
    captured.append(pool.log[-1])

    # ---- 7. distinct 路由 ----
    pool = CapturePool(rows=[(USER_ID,), (None,), ("other",)])
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_distinct():
        await coll.distinct("user_id", {"tenant_id": "bonc-2331b8a0ecdbd2ebcbf253c4"})

    asyncio.run(cap_distinct())
    captured.append(pool.log[-1])

    # ---- 8. aggregate：首阶段 $match/$sort 路由 + $group  doc 路径 ----
    pool = CapturePool(rows=[('{"_id": "active", "n": 2}',)])
    coll = PgCollection(pool, "chat_sessions", SCHEMA)

    async def cap_aggregate():
        pipeline = [
            {"$match": {"user_id": USER_ID}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ]
        await coll.aggregate(pipeline).to_list(10)
        await coll.aggregate([{"$sort": {"user_id": 1}}, {"$limit": 3}]).to_list(3)

    asyncio.run(cap_aggregate())
    captured.extend(pool.log)

    # ---- 输出 ----
    lines = [
        "-- R3 兼容层端到端冒烟（自动生成，勿手改）",
        "\\set ON_ERROR_STOP on",
        "",
    ]
    for sql, params in captured:
        lines.append(inline(sql, params) + ";")
        lines.append("")
    # 收尾：清掉冒烟建的索引（不碰数据）
    lines.append(f'DROP INDEX IF EXISTS "{SCHEMA}"."smoke_chat_sessions_user_id";')
    lines.append(f'DROP INDEX IF EXISTS "{SCHEMA}"."smoke_uq_chat_sessions_status";')
    lines.append("")
    out = "\n".join(lines)
    print(out)


if __name__ == "__main__":
    main()
