#!/usr/bin/env python3
"""扫描代码里的集合名，生成 PanWeiDB 建表 DDL。

MongoDB 的集合是「首次写入隐式创建」，PanWeiDB 的表必须显式建。本工具把
代码里的集合常量/字面量汇总成一份幂等 DDL，供迁移前的建表与巡检使用。

集合名的三个来源（取并集）：

1. ``*_COLLECTION = "name"`` / ``*_COLLECTION: str = "name"`` 常量；
2. ``db["name"]`` / ``get_db()["name"]`` 之类的字面量下标；
3. ``TENANT_SCOPED_COLLECTIONS`` / ``SETUP_SCOPED_COLLECTIONS`` 等清单字面量。

用法::

    # 打印 DDL
    python scripts/pg/generate_ddl.py --schema mogo_dev

    # 写文件
    python scripts/pg/generate_ddl.py --schema mogo_dev --out deploy/pg/schema.sql

    # 连库巡检：哪些表还没建
    python scripts/pg/generate_ddl.py --schema mogo_dev --check \
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
    # NAME_COLLECTION = "value"  /  NAME_COLLECTION: str = "value"
    re.compile(rf"^[A-Z][A-Z0-9_]*_COLLECTION\s*(?::\s*str\s*)?=\s*[\"']({COLLECTION_NAME})[\"']", re.M),
    # db["value"] / get_db()["value"]
    re.compile(rf"\bdb\[[\"']({COLLECTION_NAME})[\"']\]"),
    re.compile(rf"get_db\(\)\[[\"']({COLLECTION_NAME})[\"']\]"),
    # *COLLECTIONS = [ "a", "b", ... ]（跨行）
    re.compile(rf"^[A-Z][A-Z0-9_]*_COLLECTIONS\s*(?::\s*list\[str\]\s*)?=\s*\[([^\]]*)\]", re.M | re.S),
)
LIST_ITEM = re.compile(rf"[\"']({COLLECTION_NAME})[\"']")


def collect_names(services: tuple[str, ...] = SERVICES) -> dict[str, set[str]]:
    """返回 ``{集合名: {来源文件, ...}}``。"""
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


def table_ddl(schema: str, collection: str) -> str:
    return f"""CREATE TABLE IF NOT EXISTS "{schema}"."{collection}" (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);"""


def index_ddl(schema: str, collection: str) -> str:
    # jsonb_ops（而非 jsonb_path_ops）：PanWeiDB 3.2 未提供 jsonb_path_ops 算子类，
    # 且 jsonb_ops 额外支持 ? / ?& / ?| 等键存在性算子。
    return (
        f'CREATE INDEX IF NOT EXISTS "{collection}_tenant_idx" '
        f'ON "{schema}"."{collection}" (tenant_id);\n'
        f'CREATE INDEX IF NOT EXISTS "{collection}_doc_gin" '
        f'ON "{schema}"."{collection}" USING GIN (doc jsonb_ops);'
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
    args = parser.parse_args()

    found = collect_names()
    names = sorted(found)
    if args.list:
        for name in names:
            sources = ", ".join(sorted(found[name])[:3])
            more = "" if len(found[name]) <= 3 else f" (+{len(found[name]) - 3})"
            print(f"{name:<42} {sources}{more}")
        print(f"\n共 {len(names)} 个集合")
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
