#!/usr/bin/env python3
"""扫描代码里的集合名，生成 PanWeiDB 建表 DDL。

MongoDB 的集合是「首次写入隐式创建」，PanWeiDB 的表必须显式建。本工具把
集合清单汇总成一份幂等 DDL，供迁移前的建表与巡检使用。

**集合清单的两个来源**（默认取并集）：

1. **源 MongoDB 的实际集合**（``--from-mongo``，**权威来源**）。
   MongoDB 是事实来源，代码里动态拼出来的集合名（如配置项
   ``settings.jobs_collection``）静态扫描看不到。
2. **静态扫描代码**（无 ``--from-mongo`` 时的唯一来源，用于全新部署）。
   覆盖四种写法：``*_COLLECTION = "name"`` 常量、``db["name"]`` 字面量下标、
   ``*_COLLECTIONS = [...]`` 清单，以及大小写混合的集合常量。

> ⚠️ **静态扫描有已知漏扫**：集合名若来自配置项、f-string 拼接或变量传递
> （例如 document-parser 的 ``settings.jobs_collection``），扫描不到。
> 因此**做迁移时务必加 ``--from-mongo``**，否则 DDL 会漏表（漏掉的表会在业务
> 首次写入时由兼容层隐式创建，不至于失败，但巡检与容量规划会失真）。

用法::

    # 迁移场景（权威）：并上源 MongoDB 的实际集合
    python scripts/pg/generate_ddl.py --schema mogo_dev \\
        --from-mongo "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \\
        --out deploy/pg/schema.sql

    # 全新部署：仅静态扫描
    python scripts/pg/generate_ddl.py --schema mogo_dev --list

    # 连库巡检：哪些表还没建
    python scripts/pg/generate_ddl.py --schema mogo_dev --check \\
        --dsn "host=127.0.0.1 port=5432 user=boncuser password=... dbname=bonc"

注意：表结构固定为 ``(id, tenant_id, doc, created_at, updated_at)``，
字段一律走 JSONB 路径访问，因此**新增业务字段不需要改 DDL**。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("admin-api", "chat-api", "document-parser")

# 集合名一律是 snake_case；用白名单式字符集避免把模板串/变量名混进来。
COLLECTION_NAME = r"[a-z][a-z0-9_]*"

PATTERNS = (
    # NAME_COLLECTION = "value"  /  NAME_COLLECTION: str = "value"（允许缩进）
    re.compile(rf"^\s*[A-Z][A-Z0-9_]*_COLLECTION\s*(?::\s*str\s*)?=\s*[\"']({COLLECTION_NAME})[\"']", re.M),
    # 数据库句柄的字面量下标：db["value"] / self._db["value"] / get_db()["value"]。
    # 刻意只匹配句柄名（db / _db / database / mongo_db 等），不用「任意下标」——
    # 后者会把 mapping["key"] 之类 900 多个非集合字符串全收进来。
    re.compile(rf"(?:\b(?:db|database|mongo_db|self\._?db)\[|get_db\(\)\[)[\"']({COLLECTION_NAME})[\"']\]"),
    # *COLLECTIONS = [ "a", "b", ... ]（跨行）
    re.compile(rf"^\s*[A-Z][A-Z0-9_]*_COLLECTIONS\s*(?::\s*list\[str\]\s*)?=\s*\[([^\]]*)\]", re.M | re.S),
)
LIST_ITEM = re.compile(rf"[\"']({COLLECTION_NAME})[\"']")


def collect_names(services: tuple[str, ...] = SERVICES) -> dict[str, set[str]]:
    """静态扫描代码，返回 ``{集合名: {来源文件, ...}}``。"""
    found: dict[str, set[str]] = {}
    for service in services:
        root = REPO_ROOT / "services" / service / "app"
        if not root.is_dir():
            print(f"warn: {root} 不存在，跳过", file=sys.stderr)
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(REPO_ROOT))
            for pattern in PATTERNS:
                for match in pattern.finditer(text):
                    groups = match.groups()
                    if len(groups) == 1 and "[" in match.group(0) and match.group(0).rstrip().endswith("]"):
                        # 清单字面量：组里是一串引号包裹的名字
                        for name in LIST_ITEM.findall(groups[0]):
                            found.setdefault(name, set()).add(rel)
                    else:
                        found.setdefault(groups[0], set()).add(rel)
    return found


def collect_names_from_mongo(uri: str, db_name: str) -> dict[str, set[str]]:
    """从源 MongoDB 读取实际集合名（权威来源）。"""
    try:
        from pymongo import MongoClient
    except ImportError:
        print("error: --from-mongo 需要 pymongo（pip install pymongo）", file=sys.stderr)
        raise SystemExit(2)
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    names = [n for n in client[db_name].list_collection_names() if not n.startswith("system.")]
    source = f"{uri}/{db_name}"
    print(f"源 MongoDB {source} 有 {len(names)} 个集合", file=sys.stderr)
    return {name: {source} for name in names}


def table_ddl(schema: str, collection: str) -> str:
    return f"""CREATE TABLE IF NOT EXISTS "{schema}"."{collection}" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);"""


def index_ddl(schema: str, collection: str) -> str:
    """生成索引语句。

    **只建 ``tenant_id`` 的 btree 索引，不建 GIN。**

    原因（2026-10-13 实测，openGauss 内核的缺陷）：``USING GIN (doc jsonb_ops)``
    在遇到**任何空字符串值**时直接报错::

        jsonb_gin.cpp : 519 : The parameter destMax is equal to zero or larger
        than the macro : SECUREC_STRING_MAX_LEN

    空串在真实数据里极其常见（``email: ""`` / ``phone: ""`` / ``description: ""``），
    且顶层与嵌套值都会触发。更麻烦的是：**表里只要已有一行含空串，连 ``CREATE INDEX``
    本身都会失败**，因此不能靠「先建索引再灌数据」绕开。

    实测对照（同一张表、同样的含空串数据）：

    ======================  ==============
    索引类型                 结果
    ======================  ==============
    无索引                   ✅ 可写
    ``btree (tenant_id)``    ✅ 可写
    ``btree ((doc #> '{f}'))``  ✅ 可写（兼容层 ``create_index`` 用的形态）
    ``GIN (doc jsonb_ops)``  ❌ 报错
    ======================  ==============

    代价很小：GIN 只服务于 JSONB 包含/键存在性查询（``@>`` / ``?``），而兼容层里
    只有 ``$all`` 用到 ``@>``（全代码库 1 处）。按字段过滤走
    ``doc #> '{f}'`` 表达式索引（由各服务启动时的 ``ensure_indexes()`` 建立），
    租户过滤走 ``tenant_id``，主键查询走主键索引。
    """
    return (
        f'CREATE INDEX IF NOT EXISTS "{collection}_tenant_idx" '
        f'ON "{schema}"."{collection}" (tenant_id);'
    )


def build_sql(schema: str, names: list[str], *, with_indexes: bool = True) -> str:
    header = [
        "-- 由 scripts/pg/generate_ddl.py 生成，请勿手工编辑。",
        "-- 表结构约定见 docs/mongo-to-panweidb-migration-plan.md。",
        "",
        f'CREATE SCHEMA IF NOT EXISTS "{schema}";',
        "",
    ]
    body: list[str] = []
    for name in names:
        body.append(table_ddl(schema, name))
        if with_indexes:
            body.append(index_ddl(schema, name))
        body.append("")
    return "\n".join(header + body)


def check_missing(dsn: str, schema: str, names: list[str]) -> int:
    """连库巡检：返回缺失表数量。"""
    try:
        import psycopg
    except ImportError:
        print("error: 巡检模式需要 psycopg（pip install 'psycopg[binary]'）", file=sys.stderr)
        return 2
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        existing = {row[0] for row in cur.fetchall()}
    missing = [n for n in names if n not in existing]
    print(f"schema={schema} 已有 {len(existing)} 张表；期望 {len(names)} 张")
    if missing:
        print(f"缺失 {len(missing)} 张：")
        for name in missing:
            print(f"  - {name}")
    else:
        print("✅ 全部表已就位")
    return len(missing)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 PanWeiDB 建表 DDL")
    parser.add_argument("--schema", default="mogo_dev", help="目标 schema（默认 mogo_dev）")
    parser.add_argument("--out", help="输出 SQL 文件；缺省打印到 stdout")
    parser.add_argument("--no-indexes", action="store_true", help="不生成索引语句")
    parser.add_argument("--check", action="store_true", help="连库巡检缺失的表")
    parser.add_argument("--dsn", help="巡检用的 libpq 连接串")
    parser.add_argument("--list", action="store_true", help="只列出集合名与来源")
    parser.add_argument("--from-mongo", metavar="URI", help="源 MongoDB 连接串（权威来源，迁移场景必加）")
    parser.add_argument("--mongo-db", default="mogo_dev", help="源 MongoDB 库名（配合 --from-mongo）")
    args = parser.parse_args()

    found = collect_names()
    static_count = len(found)
    if args.from_mongo:
        for name, sources in collect_names_from_mongo(args.from_mongo, args.mongo_db).items():
            found.setdefault(name, set()).update(sources)
    names = sorted(found)
    if args.list:
        for name in names:
            sources = ", ".join(sorted(found[name])[:3])
            more = "" if len(found[name]) <= 3 else f" (+{len(found[name]) - 3})"
            print(f"{name:<42} {sources}{more}")
        print(f"\n共 {len(names)} 个集合（静态扫描 {static_count} 个）")
        return 0

    if args.check:
        if not args.dsn:
            print("error: --check 需要 --dsn", file=sys.stderr)
            return 2
        return 1 if check_missing(args.dsn, args.schema, names) else 0

    sql = build_sql(args.schema, names, with_indexes=not args.no_indexes)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(sql, encoding="utf-8")
        print(f"✅ 已写入 {out_path}（{len(names)} 个集合）")
    else:
        print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
