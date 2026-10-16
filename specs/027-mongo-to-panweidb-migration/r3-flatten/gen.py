#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 027-R3 文档 §3 表格, 按 §8.A 类型映射规则推断每列类型,
生成 openGauss/PanWeiDB 迁移 SQL (加列 / 回填 / 索引) 与类型审查清单。
仅生成文件, 不改库。"""
import re, os

DOC = "/Users/cooper/Github/mogo/docs/027-r3-relational-four-tables-plan.md"
OUT = "/tmp/migration"
os.makedirs(OUT, exist_ok=True)

BASE_COLS = {"id", "tenant_id", "created_at", "updated_at"}
SCHEMA = "mogo_dev"

# ---- 类型推断规则 ----
JSONB_SET = {
    "data", "config", "settings", "graph_data", "rules", "overrides", "tags",
    "member_ids", "participant_ids", "path_ids", "path_names", "source_chunk_ids",
    "shortcuts", "job_config", "variables", "hooks", "capabilities", "headers",
    "query_templates", "layout_overrides", "block_settings", "custom_css",
    "schedule", "triggers", "pages",
}
BOOL_SET = {"is_default", "mfa_enabled", "enabled", "verified", "used", "can_reshare", "published"}
TIME_SET = {"start_date", "end_date"}
INT_SET = {
    "sort_order", "ordinal", "priority", "progress", "failed_login_count",
    "raw_chunk_count", "rag_chunk_count", "chunk_count", "indexed_chunk_count",
}
BIGINT_SET = {"file_size", "quota_limit"}


def infer_type(col: str) -> str:
    c = col.strip()
    if c in JSONB_SET:
        return "JSONB"
    if c in BOOL_SET:
        return "BOOLEAN"
    if c in TIME_SET:
        return "TIMESTAMPTZ"
    if c in BIGINT_SET:
        return "BIGINT"
    if c in INT_SET:
        return "INTEGER"
    if c.endswith("_at"):
        return "TIMESTAMPTZ"
    if c.endswith("_count"):
        return "INTEGER"
    if c.startswith("is_") or c.endswith("_enabled"):
        return "BOOLEAN"
    if c == "version":
        return "TEXT"
    return "TEXT"


# ---- 解析文档 §3 表格 ----
def parse_doc(path):
    tables = []  # list of dict
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    # 仅匹配 §3 数据行: 以 | 序号 | 开头
    row_re = re.compile(r"^\|\s*(\d+)\s*\|")
    for ln in lines:
        if not row_re.match(ln):
            continue
        parts = [p.strip() for p in ln.split("|")]
        # ['', 序号, 表名, 决策, 平铺列集, 保留doc, 约束, '']
        if len(parts) < 7:
            continue
        seq = parts[1]
        name = parts[2]
        decision_raw = parts[3]
        flat = parts[4]
        retained = parts[5]
        constraint = parts[6] if len(parts) > 6 else ""
        flat_cols = [c.strip() for c in flat.split(",") if c.strip()]
        retained_cols = [c.strip() for c in retained.split(",") if c.strip() and c.strip() != "—"]
        if decision_raw.startswith("✅"):
            decision = "full"
        elif decision_raw.startswith("🔶"):
            decision = "partial"
        elif decision_raw.startswith("❌"):
            decision = "none"
        else:
            # emoji 变体字节差异导致 startswith 失败 -> 以平铺列集非空兜底
            decision = "flat" if flat_cols else "none"
        tables.append({
            "seq": seq, "name": name, "decision": decision,
            "flat_cols": flat_cols, "retained": retained_cols,
            "constraint": constraint,
        })
    return tables


# ---- 生成 SQL ----
def gen(tables):
    add_sql, back_sql, idx_sql = [], [], []
    review = []  # (seq, name, decision, col, type, doc_key, is_jsonb)
    for t in tables:
        name = t["name"]
        if t["decision"] == "none":
            continue
        # 加列 (openGauss 不支持 ADD COLUMN IF NOT EXISTS, 改用 DO 块判断, 可重跑)
        for col in t["flat_cols"]:
            if col in BASE_COLS:
                continue
            typ = infer_type(col)
            add_sql.append(
                f"DO $$\nBEGIN\n"
                f"  IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                f"WHERE table_schema='{SCHEMA}' AND table_name='{name}' AND column_name='{col}') THEN\n"
                f"    ALTER TABLE {SCHEMA}.{name} ADD COLUMN {col} {typ};\n"
                f"  END IF;\nEND $$;\n"
            )
            review.append((t["seq"], name, t["decision"], col, typ, col, typ == "JSONB"))
        # 回填
        for col in t["flat_cols"]:
            if col in BASE_COLS:
                continue
            typ = infer_type(col)
            if typ == "JSONB":
                back_sql.append(
                    f"UPDATE {SCHEMA}.{name} SET {col} = doc->'{col}' WHERE doc->'{col}' IS NOT NULL;")
            else:
                back_sql.append(
                    f"UPDATE {SCHEMA}.{name} SET {col} = CAST(doc->>'{col}' AS {typ}) "
                    f"WHERE doc->>'{col}' IS NOT NULL;")
        # 索引
        cons = t["constraint"].strip()
        if cons and cons not in ("—", "-"):
            m = re.search(r"\(([^)]+)\)(.*)$", cons, re.S)
            if m:
                inner = m.group(1).strip()
                rest = m.group(2).strip()
                cols = [c.strip() for c in inner.split(",") if c.strip()]
                is_unique = bool(re.search(r"WHERE", rest, re.I))
                idx_name = f"{'uq' if is_unique else 'idx'}_{name}_{'_'.join(cols[:2])}"[:63]
                on_clause = f"({', '.join(cols)})"
                if is_unique:
                    idx_sql.append(
                        f"CREATE UNIQUE INDEX {idx_name} ON {SCHEMA}.{name} {on_clause} {rest};")
                else:
                    idx_sql.append(
                        f"CREATE INDEX {idx_name} ON {SCHEMA}.{name} {on_clause};")
    return add_sql, back_sql, idx_sql, review


def main():
    tables = parse_doc(DOC)
    print(f"[parse] 解析到表格行: {len(tables)}")
    dec_counts = {}
    for t in tables:
        dec_counts[t["decision"]] = dec_counts.get(t["decision"], 0) + 1
    print(f"[parse] 决策分布: {dec_counts}")

    add_sql, back_sql, idx_sql, review = gen(tables)

    with open(os.path.join(OUT, "01_add_columns.sql"), "w", encoding="utf-8") as f:
        f.write("-- 01 加列 (按文档 §3 平铺列集; openGauss A 模式)\n")
        f.write("-- openGauss 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS\n")
        f.write("-- → 用 DO 块查 information_schema.columns 判断, 可重复执行\n\n")
        f.write("\n".join(add_sql) + "\n")
    with open(os.path.join(OUT, "02_backfill.sql"), "w", encoding="utf-8") as f:
        f.write("-- 02 数据回填: 从 doc JSONB 提取**同名列**写入新列\n")
        f.write("-- 注意1: 大表 UPDATE 可能锁表, 建议分批/低峰执行\n")
        f.write("-- 注意2: doc 早期为 Mongo 字段名(与列名存在别名差), "
                "同名列遗漏的列由 03b 高/中置信度映射补齐\n\n")
        f.write("\n".join(back_sql) + "\n")
    with open(os.path.join(OUT, "03_indexes.sql"), "w", encoding="utf-8") as f:
        f.write("-- 03 索引/部分唯一索引 (按文档 §3 约束列)\n")
        f.write("-- 带 WHERE deleted_at IS NULL 的生成 UNIQUE 部分索引; 其余普通索引\n\n")
        f.write("\n".join(idx_sql) + "\n")

    # 审查清单
    with open(os.path.join(OUT, "column_types.md"), "w", encoding="utf-8") as f:
        f.write("# 列类型推断审查清单 (027-R3 扁平化)\n\n")
        f.write("生成依据: 文档 §3 平铺列集 + §8.A 类型映射 + 命名规则推断。\n")
        f.write("doc_key 默认等于列名 (兼容层 COLUMN_MAP 通常 1:1 同名)。\n\n")
        cur = None
        for seq, name, dec, col, typ, dk, isj in review:
            if name != cur:
                cur = name
                dec_cn = {"full": "✅全平铺", "partial": "🔶部分平铺"}.get(dec, dec)
                f.write(f"\n## {seq}. {name}  [{dec_cn}]\n\n")
                f.write("| 列名 | 推断类型 | doc_key | JSONB |\n")
                f.write("|------|---------|---------|-------|\n")
            f.write(f"| {col} | {typ} | {dk} | {'是' if isj else ''} |\n")

    print(f"[gen] 加列语句: {len(add_sql)}")
    print(f"[gen] 回填语句: {len(back_sql)}")
    print(f"[gen] 索引语句: {len(idx_sql)}")
    print(f"[gen] 审查清单条目: {len(review)}")
    print(f"[gen] 输出目录: {OUT}")


if __name__ == "__main__":
    main()
