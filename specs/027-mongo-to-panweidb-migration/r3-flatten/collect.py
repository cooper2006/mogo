#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成收集 SQL: 提取 44 张平铺表 doc 中出现过的所有 key, 导出供匹配分析。"""
import re, os

DOC = "/Users/cooper/Github/mogo/docs/027-r3-relational-four-tables-plan.md"
OUT = "/tmp/migration"

def parse_flat_tables(path):
    tables = []
    row_re = re.compile(r"^\|\s*(\d+)\s*\|")
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            if not row_re.match(ln):
                continue
            parts = [p.strip() for p in ln.split("|")]
            if len(parts) < 7:
                continue
            name = parts[2]
            dec = parts[3]
            flat = [c.strip() for c in parts[4].split(",") if c.strip()]
            if dec.startswith("✅") or dec.startswith("🔶") or (not dec.startswith("❌") and flat):
                tables.append((name, flat))
    return tables

def main():
    tables = parse_flat_tables(DOC)
    lines = []
    for name, _ in tables:
        lines.append(
            f"select '{name}' as tbl, k from (select jsonb_object_keys(doc) as k "
            f"from mogo_dev.{name}) s"
        )
    sql = "\nunion all\n".join(lines) + ";\n"
    with open(os.path.join(OUT, "collect_keys.sql"), "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"[collect] 平铺表数: {len(tables)}; 已生成 collect_keys.sql")

if __name__ == "__main__":
    main()
