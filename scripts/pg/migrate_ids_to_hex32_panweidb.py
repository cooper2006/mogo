#!/usr/bin/env python3
"""PanWeiDB（openGauss / PostgreSQL 兼容）实体主键统一 32-hex 迁移脚本。

背景
----
阶段 2（``83bd0973``）把代码终态收敛为「实体主键只认 32-hex」，并配套
``scripts/migrate_ids_to_hex32.py`` 完成了 Mongo ``mogo_dev`` 的全库归一。
远端离线部署用的是 PanWeiDB ``public``（``172.17.5.145:17700`` / ``mogo``），
该库仍是 24-hex 遗留主键快照，导致浏览器编辑用户时
``PUT /admin-api/api/v1/directory/users/{id}`` 返回 400「用户ID无效」。
参见 ``docs/id-unification-hex32-runbook.md`` 与
``docs/mongo-vs-panweidb-data-diff-2026-11-11.md``。

与 Mongo 版的关键差异
----------------------
* 表结构 ``(id TEXT PRIMARY KEY, tenant_id, doc JSONB NOT NULL, created_at, updated_at)``，
  ``doc`` 内另存 ``_id`` 原值：列与 JSONB 必须同时改写；
* R3 扁平化映射列（``user_id`` / ``session_id`` / ``created_by`` / ``parent_id`` …）
  与 doc 双写，必须按同一映射表同步改写，否则查询错位；
* 复合键（``"<doc_id>:raw:raw_000001"``、角色键）含 24-hex 子串，用带边界的正则做子串替换，
  不会误伤已是 32-hex 的主键；
* 业务自然键（``org_units`` 的 ``13000``、``projects`` 的 ``default``、
  ``system_bootstrap`` 的 ``singleton`` …）不含 24-hex 子串，天然不参与转换；
* 事件流两表按阶段 2 决策截断重建（与 mongo 侧现状一致）。

安全设计
--------
* ``plan`` 全程**只读事务**，只产出 ``plan.json`` / ``id_map.json``，不写库；
* ``apply`` / ``rollback`` 必须显式 ``--confirm-stopped``；
* 每张表先 ``CREATE TABLE ... AS SELECT`` 建库内备份，再原地 UPDATE；
  全过程**单事务**，任何异常自动回滚，原表不受影响；
* ``apply`` 末尾自动 ``verify``，verify 失败则不提交；
* ``rollback`` 从库内备份表整表恢复；备份表保留到人工确认后再清理。

子命令
------
    plan      只读盘点：全库收集 24-hex 值、生成映射表与统计报告
    apply     写库：备份 -> 改写 id/doc/扁平化列 -> 截断事件流 -> 自动 verify
    verify    断言：零 24-hex 主键、零 doc/列内 24-hex 引用、事件流为空、行数一致
    rollback  从 ``plan.json`` 记录的库内备份表恢复

连接串默认从仓库根 ``.env`` 的 ``PANWEIDB_*`` 构造，也可用 ``--dsn`` 覆盖。

示例
----
    # 只读盘点（可连生产库，不写）
    python3 scripts/pg/migrate_ids_to_hex32_panweidb.py \
        --out backups/hex32-pw-plan plan

    # 独立 schema 演练（先自行 CREATE SCHEMA + 复制副本，再跑全流程）
    python3 scripts/pg/migrate_ids_to_hex32_panweidb.py \
        --schema hex32_rehearsal --out backups/hex32-pw-rehearsal \
        --confirm-stopped apply
    python3 scripts/pg/migrate_ids_to_hex32_panweidb.py \
        --schema hex32_rehearsal --out backups/hex32-pw-rehearsal verify
    python3 scripts/pg/migrate_ids_to_hex32_panweidb.py \
        --schema hex32_rehearsal --out backups/hex32-pw-rehearsal \
        --confirm-stopped rollback

    # 停机窗口正式执行
    python3 scripts/pg/migrate_ids_to_hex32_panweidb.py \
        --schema public --out backups/hex32-pw-20261112T000000Z \
        --confirm-stopped apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from psycopg import connect
    from psycopg import sql
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover
    print(f"error: 缺少依赖 {exc.name}（需要 psycopg[binary] 3.x）", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[2]

#: 精确 24-hex（ObjectId 字符串），带前后 hex 边界，避免把 32-hex 当成 24-hex。
HEX24_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{24}(?![0-9a-fA-F])")
HEX24_FULL_RE = re.compile(r"^[0-9a-fA-F]{24}$")
HEX32_FULL_RE = re.compile(r"^[0-9a-fA-F]{32}$")
NATURAL_KEY_RE = re.compile(r"^(?:[0-9a-fA-F]{24}|[0-9a-fA-F]{32})$")

#: 阶段 2 决策：事件流日志集合截断重建，不做逐行改写。
EVENT_TABLES = ("kernel_event_inbox", "kernel_event_projections")

#: 表必须具备这两列才纳入迁移范围（其余为系统表 / 迁移进度表）。
REQUIRED_COLUMNS = {"id", "doc"}

#: 备份表前缀；备份名用序号而非原表名，规避 PG 63 字节标识符上限。
BACKUP_PREFIX = "h32bak_"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def build_dsn(explicit: str | None) -> tuple[str, str]:
    if explicit:
        return explicit, "public"
    env = load_env()
    required = ("PANWEIDB_HOST", "PANWEIDB_PORT", "PANWEIDB_USER", "PANWEIDB_PASSWORD", "PANWEIDB_DB")
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise SystemExit(f"error: .env 缺少 {', '.join(missing)}，或改用 --dsn")
    dsn = (
        f"host={env['PANWEIDB_HOST']} port={env['PANWEIDB_PORT']} "
        f"user={env['PANWEIDB_USER']} password={env['PANWEIDB_PASSWORD']} "
        f"dbname={env['PANWEIDB_DB']} connect_timeout=10"
    )
    return dsn, env.get("PANWEIDB_SCHEMA", "public")


def new_id_for(legacy: str) -> str:
    """24-hex -> 32-hex，确定性且时间有序。

    前 12 位取 ObjectId 前 4 字节（Unix 秒）转毫秒，保留 ``_id`` 作为
    高水位 / 分页游标的字典序语义；后 20 位取 sha256 摘要，保证重跑幂等。
    """
    value = legacy.lower()
    ts_ms = int(value[:8], 16) * 1000
    prefix = f"{ts_ms & ((1 << 48) - 1):012x}"
    suffix = hashlib.sha256(("mogo-hex32-v1:" + value).encode()).hexdigest()[:20]
    return prefix + suffix


class Mapper:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.data: dict[str, str] = dict(initial or {})
        self.added: set[str] = set()

    def lookup(self, legacy: str) -> str:
        key = legacy.lower()
        if key not in self.data:
            self.data[key] = new_id_for(key)
            self.added.add(key)
        return self.data[key]

    def transform(self, value: Any) -> Any:
        """递归改写字符串 / 列表 / 字典中的 24-hex 子串。"""
        if isinstance(value, str):
            return HEX24_RE.sub(lambda m: self.lookup(m.group(0)), value)
        if isinstance(value, list):
            return [self.transform(v) for v in value]
        if isinstance(value, dict):
            return {k: self.transform(v) for k, v in value.items()}
        return value

    def collect(self, value: Any) -> None:
        if isinstance(value, str):
            for match in HEX24_RE.finditer(value):
                self.lookup(match.group(0))
        elif isinstance(value, list):
            for item in value:
                self.collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                self.collect(item)


def discover_tables(conn, schema: str) -> dict[str, list[tuple[str, str]]]:
    """返回 ``table -> [(column, data_type)]``，仅含 id+doc 且非备份表。"""
    rows = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s ORDER BY table_name, ordinal_position",
        (schema,),
    ).fetchall()
    tables: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in rows:
        if table.startswith(BACKUP_PREFIX):
            continue
        tables.setdefault(table, []).append((column, data_type))
    return {
        t: cols
        for t, cols in tables.items()
        if REQUIRED_COLUMNS <= {c for c, _ in cols}
    }


def read_all(conn, schema: str, table: str, cols: list[tuple[str, str]]) -> list[tuple]:
    query = sql.SQL("SELECT {} FROM {}.{}").format(
        sql.SQL(", ").join(sql.Identifier(c) for c, _ in cols),
        sql.Identifier(schema),
        sql.Identifier(table),
    )
    return conn.execute(query).fetchall()


def count_rows(conn, schema: str, table: str) -> int:
    return int(
        conn.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        ).fetchone()[0]
    )


def out_dir(raw: str | None, stamp: str) -> Path:
    path = Path(raw) if raw else ROOT / "backups" / f"hex32-panweidb-{stamp}"
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def do_plan(conn, schema: str, out: Path, stamp: str) -> None:
    conn.execute("SET TRANSACTION READ ONLY")
    tables = discover_tables(conn, schema)
    mapper = Mapper()
    report: dict[str, Any] = {
        "schema": schema,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stamp": stamp,
        "tables": {},
        "event_tables": {},
        "totals": {},
    }

    grand = {"rows": 0, "hex24_ids": 0, "hex32_ids": 0, "natural_ids": 0, "rows_with_hex24": 0}
    for idx, (table, cols) in enumerate(sorted(tables.items())):
        if table in EVENT_TABLES:
            rows = count_rows(conn, schema, table)
            report["event_tables"][table] = {"rows": rows, "action": "truncate"}
            continue
        rows = read_all(conn, schema, table, cols)
        hex24 = hex32 = natural = affected = 0
        for row in rows:
            values = dict(zip((c for c, _ in cols), row))
            ident = str(values.get("id") or "")
            if HEX24_FULL_RE.match(ident):
                hex24 += 1
            elif HEX32_FULL_RE.match(ident):
                hex32 += 1
            else:
                natural += 1
            before = len(mapper.data)
            for value in row:
                mapper.collect(value)
            if any(
                HEX24_RE.search(v)
                for v in row
                if isinstance(v, str)
            ) or len(mapper.data) > before:
                affected += 1
        report["tables"][table] = {
            "order": idx,
            "rows": len(rows),
            "hex24_ids": hex24,
            "hex32_ids": hex32,
            "natural_ids": natural,
            "rows_with_hex24": affected,
            "columns": [c for c, _ in cols],
            "backup": f"{BACKUP_PREFIX}{idx:03d}_{stamp}",
        }
        for key, value in (("rows", len(rows)), ("hex24_ids", hex24), ("hex32_ids", hex32),
                           ("natural_ids", natural), ("rows_with_hex24", affected)):
            grand[key] += value

    report["totals"] = grand
    report["mapping_size"] = len(mapper.data)
    report["event_rows_total"] = sum(v["rows"] for v in report["event_tables"].values())
    write_json(out / "plan.json", report)
    write_json(out / "id_map.json", mapper.data)
    print(f"[plan] schema={schema} tables={len(tables)} non_event_tables={len(report['tables'])}")
    print(f"[plan] {grand}")
    print(f"[plan] event_rows_to_truncate={report['event_rows_total']} mapping={len(mapper.data)}")
    print(f"[plan] 报告: {out / 'plan.json'} / {out / 'id_map.json'}")


def load_report(out: Path) -> tuple[dict[str, Any], Mapper]:
    plan_path = out / "plan.json"
    if not plan_path.is_file():
        raise SystemExit(f"error: 缺少 {plan_path}，请先运行 plan")
    report = json.loads(plan_path.read_text(encoding="utf-8"))
    map_path = out / "id_map.json"
    initial = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else {}
    return report, Mapper(initial)


def do_apply(conn, schema: str, out: Path, report: dict[str, Any], mapper: Mapper) -> None:
    if report.get("schema") != schema:
        raise SystemExit(f"error: plan 的 schema={report.get('schema')}，当前 --schema={schema}，拒绝跨 schema 执行")
    tables = discover_tables(conn, schema)
    manifest: dict[str, Any] = {
        "schema": schema,
        "stamp": report["stamp"],
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
        "event_tables": list(report["event_tables"]),
    }

    # 1) 全库备份（原地 UPDATE 前的完整快照，含事件流）
    for table in sorted(report["tables"]):
        cols = tables.get(table)
        if cols is None:
            raise SystemExit(f"error: 表 {table} 已不存在，中止")
        backup = report["tables"][table]["backup"]
        conn.execute(
            sql.SQL("CREATE TABLE {}.{} AS SELECT * FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(backup),
                sql.Identifier(schema), sql.Identifier(table),
            )
        )
        manifest["tables"][table] = {"backup": backup, "columns": [c for c, _ in cols]}
    for table in report["event_tables"]:
        if table not in tables:
            continue
        backup = f"{BACKUP_PREFIX}event_{table}_{report['stamp']}"[:60]
        conn.execute(
            sql.SQL("CREATE TABLE {}.{} AS SELECT * FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(backup),
                sql.Identifier(schema), sql.Identifier(table),
            )
        )
        manifest["tables"][table] = {"backup": backup, "columns": [c for c, _ in tables[table]], "event": True}
    print(f"[apply] 库内备份完成：{len(manifest['tables'])} 张")

    # 2) 逐表原地改写（id / doc / R3 扁平化列都用同一映射表）
    changed_rows = changed_ids = 0
    for table, meta in report["tables"].items():
        cols = tables[table]
        col_names = [c for c, _ in cols]
        jsonb_cols = {c for c, t in cols if t.lower() in ("jsonb", "json")}
        rows = read_all(conn, schema, table, cols)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in col_names
        )
        update = sql.SQL("UPDATE {}.{} SET {} WHERE {} = %s").format(
            sql.Identifier(schema), sql.Identifier(table), assignments, sql.Identifier("id")
        )
        for row in rows:
            before = dict(zip(col_names, row))
            after = {c: mapper.transform(v) for c, v in before.items()}
            if after == before:
                continue
            params = [Jsonb(after[c]) if c in jsonb_cols else after[c] for c in col_names]
            conn.execute(update, params + [before["id"]])
            changed_rows += 1
            if HEX24_FULL_RE.match(str(before["id"] or "")):
                changed_ids += 1
    print(f"[apply] 改写 rows={changed_rows} hex24_ids={changed_ids}")

    # 3) 事件流按决策截断
    for table in report["event_tables"]:
        if table in tables:
            conn.execute(
                sql.SQL("TRUNCATE TABLE {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
    print(f"[apply] 事件流已截断：{', '.join(report['event_tables']) or '(无)'}")

    # 4) 自动 verify（在提交前，失败则整个事务回滚）
    verify(conn, schema, report, strict_rows=True)
    print("[apply] verify PASS")

    mapping_path = out / "id_map.json"
    write_json(mapping_path, mapper.data)
    write_json(out / "manifest.json", manifest)
    print(f"[apply] manifest: {out / 'manifest.json'}")


def verify(conn, schema: str, report: dict[str, Any], strict_rows: bool = False) -> None:
    tables = discover_tables(conn, schema)
    problems: list[str] = []
    checked_rows = 0
    for table, meta in report["tables"].items():
        if table not in tables:
            problems.append(f"{table}: 表缺失")
            continue
        cols = tables[table]
        rows = read_all(conn, schema, table, cols)
        if strict_rows and len(rows) != meta["rows"]:
            problems.append(f"{table}: 行数 {len(rows)} != plan {meta['rows']}")
        hex24_ids = 0
        natural_ids = 0
        for row in rows:
            checked_rows += 1
            values = dict(zip((c for c, _ in cols), row))
            ident = str(values.get("id") or "")
            if HEX24_FULL_RE.match(ident):
                hex24_ids += 1
            if not NATURAL_KEY_RE.match(ident):
                natural_ids += 1
            for value in row:
                if isinstance(value, str) and HEX24_RE.search(value):
                    problems.append(f"{table}.{ident}: 文本列残留 24-hex")
                    break
                if isinstance(value, (dict, list)):
                    if HEX24_RE.search(json.dumps(value, ensure_ascii=False, default=str)):
                        problems.append(f"{table}.{ident}: JSONB 残留 24-hex")
                        break
        if hex24_ids:
            problems.append(f"{table}: 仍有 {hex24_ids} 个 24-hex 主键")
        if strict_rows and natural_ids != meta["natural_ids"]:
            problems.append(f"{table}: 自然键 {natural_ids} != plan {meta['natural_ids']}")
    for table in report["event_tables"]:
        if table in tables:
            left = count_rows(conn, schema, table)
            if left:
                problems.append(f"{table}: 事件流未清空（{left} 行）")
    if problems:
        raise RuntimeError("verify FAILED:\n  - " + "\n  - ".join(problems[:30]))
    print(f"[verify] PASS checked_rows={checked_rows} tables={len(report['tables'])}")


def do_rollback(conn, schema: str, out: Path) -> None:
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"error: 缺少 {manifest_path}，无法回滚")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != schema:
        raise SystemExit("error: manifest 的 schema 与 --schema 不一致，拒绝回滚")
    for table, meta in manifest["tables"].items():
        backup = meta["backup"]
        cols = meta["columns"]
        exists = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
            (schema, backup),
        ).fetchone()
        if not exists:
            raise SystemExit(f"error: 备份表 {backup} 不存在，中止回滚")
        conn.execute(
            sql.SQL("TRUNCATE TABLE {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        )
        collist = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
        conn.execute(
            sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table), collist,
                collist, sql.Identifier(schema), sql.Identifier(backup),
            )
        )
    print(f"[rollback] 已从库内备份恢复 {len(manifest['tables'])} 张表（备份表保留）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", default=None, help="libpq 连接串；默认读仓库根 .env 的 PANWEIDB_*")
    parser.add_argument("--schema", default=None, help="目标 schema；默认取 .env 的 PANWEIDB_SCHEMA 或 public")
    parser.add_argument("--out", default=None, help="报告 / 映射 / manifest 目录")
    parser.add_argument("--confirm-stopped", action="store_true", help="确认业务服务已全部停止写入")
    parser.add_argument("command", choices=["plan", "apply", "verify", "rollback"])
    args = parser.parse_args()

    dsn, default_schema = build_dsn(args.dsn)
    schema = args.schema or default_schema
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir(args.out, stamp)
    print(f"[migrate] schema={schema} command={args.command} out={out}")

    if args.command in ("apply", "rollback") and not args.confirm_stopped:
        raise SystemExit("error: 写库操作必须显式传 --confirm-stopped（并确认业务已停）")

    with connect(dsn) as conn:
        if args.command == "plan":
            do_plan(conn, schema, out, stamp)
        elif args.command == "apply":
            report, mapper = load_report(out)
            do_apply(conn, schema, out, report, mapper)
        elif args.command == "verify":
            report, _ = load_report(out)
            conn.execute("SET TRANSACTION READ ONLY")
            verify(conn, schema, report, strict_rows=True)
        elif args.command == "rollback":
            do_rollback(conn, schema, out)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, SystemExit) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
