#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 44 张平铺表的 平铺列 与 doc 实际 key 的匹配情况, 找出需语义映射的列。"""
import re, os

DOC = "/Users/cooper/Github/mogo/docs/027-r3-relational-four-tables-plan.md"
BASE = {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "deleted_at"}

def parse_flat(path):
    flat = {}
    row_re = re.compile(r"^\|\s*(\d+)\s*\|")
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            if not row_re.match(ln):
                continue
            parts = [p.strip() for p in ln.split("|")]
            if len(parts) < 7:
                continue
            name = parts[2]; dec = parts[3]
            cols = [c.strip() for c in parts[4].split(",") if c.strip()]
            if dec.startswith("✅") or dec.startswith("🔶") or (not dec.startswith("❌") and cols):
                flat[name] = cols
    return flat

def to_camel(s):
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])

def load_keys(path):
    d = {}
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if "|" not in ln:
                continue
            tbl, _, key = ln.partition("|")
            d.setdefault(tbl.strip(), set()).add(key.strip())
    return d

def main():
    flat = parse_flat(DOC)
    keys = load_keys("/tmp/migration/keys.txt")
    report = []
    empty_tables = []
    total_missing = 0
    tables_with_missing = 0
    for tbl, cols in flat.items():
        kset = keys.get(tbl, set())
        if not kset:
            empty_tables.append(tbl)
            continue
        missing = []
        for c in cols:
            if c in BASE:
                continue
            if c in kset or to_camel(c) in kset:
                continue
            missing.append(c)
        if missing:
            tables_with_missing += 1
            total_missing += len(missing)
            report.append(f"\n## {tbl}  [缺失 {len(missing)} 列 / doc keys {len(kset)} 个]")
            report.append("缺失列: " + ", ".join(missing))
            report.append("doc 实际 keys: " + ", ".join(sorted(kset)))
    with open("/tmp/migration/mapping_report.md", "w", encoding="utf-8") as f:
        f.write("# 列名 vs doc key 匹配分析报告 (027-R3 回填映射)\n\n")
        f.write(f"平铺表数: {len(flat)}; 有数据且存在缺失列的表: {tables_with_missing}; "
                f"缺失列总数(仅统计有数据表): {total_missing}\n")
        f.write(f"空表(无 doc 数据, 回填 trivially 完成, 跳过): {len(empty_tables)}\n\n")
        f.write("说明: '缺失列' = 该列名(及 camelCase 形式)在 doc 中均找不到同名 key, "
                "需确认语义别名(doc_key)才能正确回填。\n")
        f.write("\n".join(report) + "\n")
    print(f"[analyze] 平铺表 {len(flat)} | 有缺失列表 {tables_with_missing} | 缺失列总数 {total_missing}")
    print("[analyze] 报告已写 /tmp/migration/mapping_report.md")

if __name__ == "__main__":
    main()
