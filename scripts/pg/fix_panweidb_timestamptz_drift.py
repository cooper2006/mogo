#!/usr/bin/env python3
"""幂等订正 PanWeiDB 里 TIMESTAMPTZ 映射列的 UTC 偏移漂移。

背景（2026-11-04）：openGauss 3.2 / PanWeiDB A 模式的 ``::timestamptz`` 会忽略
字符串里的 ``+00:00``，把 UTC 墙钟按会话时区（PRC）解释，导致经 UPDATE 列同步
落库的时间列（如 ``chat_sessions.last_message_at``）比真实瞬时少 8 小时，
会话侧边栏因此把刚发的消息显示成「8 小时前」。列同步的修复已落在
``app/core/pg_compat.py::_column_sync_sql``，本脚本负责把**历史数据**一次刷正。

订正依据是 doc JSONB 里的原始 UTC 字符串。只处理带 UTC 标记（``+00:00`` / ``Z``）
的值，与列同步的补偿条件一致；纯日期 / 本地时间字符串保持原样。回写用参数绑定
aware datetime，绕开数据库对时间字符串的解析。仅当列值与 doc 值代表的瞬时
相差超过 1 秒才更新，因此可以重复运行。

用法（环境变量与 chat-api 一致，须能连到 PanWeiDB）::

    python scripts/pg/fix_panweidb_timestamptz_drift.py           # dry-run（默认）
    python scripts/pg/fix_panweidb_timestamptz_drift.py --apply    # 实际写入

容器内无需复制文件，直接经 stdin 执行::

    docker exec -i mogo-chat-api-1 sh -c 'set -a; . /run/askai-secrets/runtime.env; set +a; cd /app && python - --apply' \
        < scripts/pg/fix_panweidb_timestamptz_drift.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    _HERE = Path(__file__).resolve()
except NameError:  # 经 stdin（python -）执行时没有 __file__
    _HERE = Path.cwd()

for _candidate in (Path("/app"), _HERE.parents[1] / "services" / "chat-api", Path.cwd()):
    if (_candidate / "app" / "core" / "pg.py").is_file():
        sys.path.insert(0, str(_candidate))
        break
else:
    raise SystemExit("找不到 chat-api 的 app/core/pg.py；请在仓库根或 chat-api 容器内运行")

from app.core.column_map import COLUMN_MAP, COLUMN_TYPES  # noqa: E402
from app.core.pg import init_pg  # noqa: E402


def parse_utc_marker(value: object) -> datetime | None:
    """只解析带 UTC 标记的时间字符串，返回 UTC 瞬时；其余一律返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif not text.endswith("+00:00"):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.astimezone(timezone.utc)


def timestamptz_targets():
    """所有需要检查的 (table, doc_key, column)，跳过嵌套键与基础列。"""
    for table, entries in COLUMN_MAP.items():
        for key, column in entries.items():
            if COLUMN_TYPES.get(column) == "TIMESTAMPTZ" and "." not in key:
                yield table, key, column


def collect(pool, verbose: bool) -> tuple[dict[tuple[str, str], list], int, int]:
    """扫描全库，返回 {(table, column): [(id, expected, doc_raw, col_value)]}。"""
    pending: dict[tuple[str, str], list] = {}
    scanned = drift = 0
    with pool.connection() as conn:
        for table, key, column in timestamptz_targets():
            sql = (
                f'SELECT id, doc #>> \'{{{key}}}\', "{column}" '
                f'FROM "{table}" WHERE "{column}" IS NOT NULL'
            )
            try:
                rows = conn.execute(sql).fetchall()
            except Exception as exc:
                conn.rollback()  # SELECT 失败会让事务进入 aborted，必须回滚才能继续
                print(f"  skip {table}.{column}: {type(exc).__name__} {str(exc)[:90]}")
                continue
            fixes = []
            for doc_id, doc_raw, col_value in rows:
                expected = parse_utc_marker(doc_raw)
                if expected is None or not isinstance(col_value, datetime):
                    continue
                actual = (
                    col_value.astimezone(timezone.utc)
                    if col_value.tzinfo is not None
                    else col_value.replace(tzinfo=timezone.utc)
                )
                scanned += 1
                if abs((expected - actual).total_seconds()) > 1:
                    fixes.append((doc_id, expected, doc_raw, col_value))
            if fixes:
                pending[(table, column)] = fixes
                drift += len(fixes)
                print(f"  {table}.{column}: {len(fixes)}/{len(rows)} 行偏差")
                if verbose:
                    for doc_id, expected, doc_raw, col_value in fixes[:3]:
                        print(f"    id={doc_id} doc={doc_raw} col={col_value} -> {expected.isoformat()}")
        conn.rollback()  # 扫描阶段不写入
    return pending, scanned, drift


def apply(pool, pending) -> int:
    fixed = 0
    with pool.connection() as conn:
        for (table, column), fixes in pending.items():
            for doc_id, expected, _doc_raw, _col_value in fixes:
                conn.execute(
                    f'UPDATE "{table}" SET "{column}" = %s WHERE id = %s',
                    (expected, str(doc_id)),
                )
                fixed += 1
        conn.commit()
    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入（缺省只做 dry-run）")
    parser.add_argument("--verbose", action="store_true", help="打印偏差样本")
    args = parser.parse_args()

    pool = init_pg()
    try:
        pending, scanned, drift = collect(pool, args.verbose)
        print(f"\n扫描 {scanned} 行带 UTC 标记的时间值，发现 {drift} 行偏差，涉及 {len(pending)} 个列")
        if args.apply:
            fixed = apply(pool, pending)
            print(f"已订正 {fixed} 行")
        else:
            print("dry-run：未写入。确认无误后加 --apply 执行")
        return 0
    finally:
        pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
