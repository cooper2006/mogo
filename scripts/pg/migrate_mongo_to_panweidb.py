#!/usr/bin/env python3
"""MongoDB → PanWeiDB 数据搬迁工具。

把每个集合的文档原样搬进 PanWeiDB 的 ``<schema>.<collection>`` 表：

    id = str(_id)   tenant_id = doc["tenant_id"]   doc = 完整文档(JSONB)

设计取舍：

* **幂等**：写入一律 ``INSERT ... ON CONFLICT (id) DO UPDATE``。中断后**直接重跑**
  即可，无需断点续传——重跑会覆盖已写入的行，不会产生重复。
* **不传播删除**（默认）：只做 upsert，**不删除**目标库里源库已经没有的行。
  对**活跃的**源库这意味着会留残留：源库在两次搬迁之间删掉的行，目标库仍保留。
  此时 ``--verify`` 会报「目标多于源」，属预期。需要收敛时用 ``--prune``。
* **可续跑**：进度表 ``<schema>._migration_progress`` 记录每个集合的状态与计数；
  ``--resume`` 跳过已完成集合，用于大库分批搬。
* **可校验**：``--verify`` 只做「Mongo 计数 vs PanWeiDB 计数」比对，不改数据。
* **不删不改源库**：工具只读 MongoDB，只写 PanWeiDB 目标表。

用法::

    # 演练：只统计不写库
    python scripts/pg/migrate_mongo_to_panweidb.py \\
        --mongo-uri "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \\
        --dsn "host=127.0.0.1 port=5432 user=boncuser password=... dbname=bonc" \\
        --schema mogo_dev --dry-run

    # 正式搬迁
    python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev

    # 对账收敛：删除目标库里源库已不存在的行（源库在搬迁期间仍在写入时必须）
    python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev --prune

    # 搬迁后校验
    python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev --verify

**已知语义差异**（搬迁不改变，但消费侧需注意）：Mongo 的 ``ObjectId`` 在 JSONB 里
只能落成字符串，因此迁移后 ``_id`` 是 hex 字符串而非 ``ObjectId`` 对象。
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Iterable, Iterator

PROGRESS_TABLE = "_migration_progress"

CREATE_PROGRESS = f"""
CREATE TABLE IF NOT EXISTS {{qualified}} (
    collection  TEXT PRIMARY KEY,
    migrated    BIGINT NOT NULL DEFAULT 0,
    done        BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _qualified(schema: str, table: str) -> str:
    return f'"{schema}"."{table}"'


def _normalise(doc: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    """把 Mongo 文档转成 ``(id, tenant_id, doc)``。"""
    doc = dict(doc)
    raw_id = doc.get("_id")
    doc_id = str(raw_id) if raw_id is not None else ""
    if not doc_id:
        raise ValueError("文档缺少 _id，无法搬迁")
    # 统一成字符串：JSONB 存不下 ObjectId，且兼容层查询也按字符串比对。
    doc["_id"] = doc_id
    tenant_id = doc.get("tenant_id")
    return doc_id, (None if tenant_id is None else str(tenant_id)), doc


def _batched(cursor: Any, size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for doc in cursor:
        batch.append(doc)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def migrate_collection(
    mongo_db: Any,
    pg_conn: Any,
    schema: str,
    collection: str,
    *,
    batch_size: int,
    dry_run: bool,
) -> int:
    """搬迁单个集合，返回写入行数。"""
    if collection.startswith("system."):
        return 0
    total = mongo_db[collection].estimated_document_count()
    if dry_run:
        print(f"  [dry-run] {collection}: {total} 篇文档")
        return total

    qualified = _qualified(schema, collection)
    written = 0
    # 目标表由 DDL 工具预先创建；这里兜底建一次，保证独立可用。
    with pg_conn.cursor() as cur:
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS {qualified} ('
            "id TEXT PRIMARY KEY, tenant_id TEXT, doc JSONB NOT NULL, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    pg_conn.commit()

    upsert = (
        f"INSERT INTO {qualified} (id, tenant_id, doc) VALUES (%s, %s, %s::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, "
        "tenant_id = EXCLUDED.tenant_id, updated_at = now()"
    )
    cursor = mongo_db[collection].find({}, no_cursor_timeout=True)
    try:
        with pg_conn.cursor() as cur:
            for batch in _batched(cursor, batch_size):
                rows = [_normalise(doc) for doc in batch]
                # 中文/emoji 必须走 UTF-8 JSON，避免转义成 \uXXXX 后语义仍正确但体积膨胀。
                import json

                cur.executemany(
                    upsert,
                    [(doc_id, tenant_id, json.dumps(doc, ensure_ascii=False, default=str))
                     for doc_id, tenant_id, doc in rows],
                )
                pg_conn.commit()
                written += len(rows)
                print(f"  {collection}: {written}/{total}", end="\r", flush=True)
    finally:
        cursor.close()
    print(f"  {collection}: {written} 篇文档已写入" + " " * 12)
    return written


def prune_collection(mongo_db: Any, pg_conn: Any, schema: str, collection: str) -> int:
    """删除目标库中**源库已不存在**的行，返回删除数。

    用于源库在搬迁期间仍在写入的场景（例如运行中的服务有会话 GC / TTL 清理）：
    upsert 只能保证「源库有的目标库也有」，不能保证「目标库没有源库已删的」。
    加 ``--prune`` 后两边集合才真正收敛，``--verify`` 才有意义。
    """
    qualified = _qualified(schema, collection)
    ids = [str(doc["_id"]) for doc in mongo_db[collection].find({}, {"_id": 1})]
    with pg_conn.cursor() as cur:
        if not ids:
            cur.execute(f"DELETE FROM {qualified}")
        else:
            cur.execute(f"DELETE FROM {qualified} WHERE NOT (id = ANY(%s))", [ids])
        deleted = cur.rowcount
    pg_conn.commit()
    return max(deleted, 0)


def mark_progress(pg_conn: Any, schema: str, collection: str, migrated: int, done: bool) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_qualified(schema, PROGRESS_TABLE)} "
            "(collection, migrated, done, updated_at) VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (collection) DO UPDATE SET migrated = EXCLUDED.migrated, "
            "done = EXCLUDED.done, updated_at = now()",
            [collection, migrated, done],
        )
    pg_conn.commit()


def completed_collections(pg_conn: Any, schema: str) -> set[str]:
    try:
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT collection FROM {_qualified(schema, PROGRESS_TABLE)} WHERE done")
            return {row[0] for row in cur.fetchall()}
    except Exception:
        pg_conn.rollback()
        return set()


def verify(mongo_db: Any, pg_conn: Any, schema: str, collections: Iterable[str]) -> int:
    """比对计数；返回不一致的集合数。"""
    mismatches = 0
    for collection in collections:
        if collection.startswith("system."):
            continue
        expected = mongo_db[collection].estimated_document_count()
        try:
            with pg_conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {_qualified(schema, collection)}")
                actual = cur.fetchone()[0]
        except Exception:
            pg_conn.rollback()
            actual = -1
        flag = "✅" if expected == actual else "❌"
        if expected != actual:
            mismatches += 1
        print(f"  {flag} {collection:<42} mongo={expected:<8} panweidb={actual}")
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="MongoDB → PanWeiDB 数据搬迁")
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--mongo-db", required=True)
    parser.add_argument("--dsn", required=True, help="PanWeiDB 的 libpq 连接串")
    parser.add_argument("--schema", default="mogo_dev")
    parser.add_argument("--collections", nargs="*", help="只搬这些集合（缺省=全部）")
    parser.add_argument("--batch", type=int, default=500, help="每批行数（默认 500）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    parser.add_argument("--verify", action="store_true", help="只做计数校验")
    parser.add_argument("--resume", action="store_true", help="跳过已完成的集合")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="对账：删除目标库中源库已不存在的行（源库在搬迁期间仍被写入时需要）",
    )
    args = parser.parse_args()

    try:
        from pymongo import MongoClient
        import psycopg
    except ImportError as exc:
        print(f"error: 缺少依赖 {exc.name}（pip install pymongo 'psycopg[binary]'）", file=sys.stderr)
        return 2

    mongo = MongoClient(args.mongo_uri)
    mongo_db = mongo[args.mongo_db]
    collections = args.collections or sorted(
        n for n in mongo_db.list_collection_names() if not n.startswith("system.")
    )

    with psycopg.connect(args.dsn) as pg_conn:
        if args.verify:
            print(f"校验 schema={args.schema}（{len(collections)} 个集合）")
            mismatches = verify(mongo_db, pg_conn, args.schema, collections)
            print(f"\n{'✅ 计数全部一致' if not mismatches else f'❌ {mismatches} 个集合计数不一致'}")
            return 1 if mismatches else 0

        if not args.dry_run:
            with pg_conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"')
                cur.execute(CREATE_PROGRESS.format(qualified=_qualified(args.schema, PROGRESS_TABLE)))
            pg_conn.commit()

        skip = completed_collections(pg_conn, args.schema) if args.resume else set()
        if skip:
            print(f"--resume：跳过 {len(skip)} 个已完成集合")

        started = time.time()
        grand_total = 0
        pruned_total = 0
        for collection in collections:
            if collection in skip:
                continue
            count = migrate_collection(
                mongo_db, pg_conn, args.schema, collection,
                batch_size=args.batch, dry_run=args.dry_run,
            )
            grand_total += count
            if not args.dry_run:
                if args.prune:
                    removed = prune_collection(mongo_db, pg_conn, args.schema, collection)
                    if removed:
                        print(f"  {collection}: 清理 {removed} 行（源库已不存在）")
                    pruned_total += removed
                mark_progress(pg_conn, args.schema, collection, count, True)

        action = "演练统计" if args.dry_run else "已搬迁"
        print(f"\n{action} {grand_total} 篇文档，耗时 {time.time() - started:.1f}s")
        if args.prune and not args.dry_run:
            print(f"对账清理 {pruned_total} 行（源库已不存在的行）")
        if not args.dry_run:
            print("下一步：用 --verify 校验计数")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
