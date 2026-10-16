#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于 doc 实际 key, 为 107 个缺失列生成候选 doc_key 映射表 + 待执行修正回填 SQL。
不自动执行, 等用户确认。"""
import re, os

DOC = "/Users/cooper/Github/mogo/docs/027-r3-relational-four-tables-plan.md"
BASE = {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "deleted_at"}
SCHEMA = "mogo_dev"

# 类型推断 (与 gen.py 一致)
JSONB_SET = {"data","config","settings","graph_data","rules","overrides","tags","member_ids",
    "participant_ids","path_ids","path_names","source_chunk_ids","shortcuts","job_config",
    "variables","hooks","capabilities","headers","query_templates","layout_overrides",
    "block_settings","custom_css","schedule","triggers","pages"}
BOOL_SET = {"is_default","mfa_enabled","enabled","verified","used","can_reshare","published"}
TIME_SET = {"start_date","end_date"}
INT_SET = {"sort_order","ordinal","priority","progress","failed_login_count","raw_chunk_count",
    "rag_chunk_count","chunk_count","indexed_chunk_count"}
BIGINT_SET = {"file_size","quota_limit"}

def infer_type(col):
    c = col.strip()
    if c in JSONB_SET: return "JSONB"
    if c in BOOL_SET: return "BOOLEAN"
    if c in TIME_SET: return "TIMESTAMPTZ"
    if c in BIGINT_SET: return "BIGINT"
    if c in INT_SET: return "INTEGER"
    if c.endswith("_at"): return "TIMESTAMPTZ"
    if c.endswith("_count"): return "INTEGER"
    if c.startswith("is_") or c.endswith("_enabled"): return "BOOLEAN"
    if c == "version": return "TEXT"
    return "TEXT"

def parse_flat(path):
    flat = {}
    row_re = re.compile(r"^\|\s*(\d+)\s*\|")
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            if not row_re.match(ln): continue
            parts = [p.strip() for p in ln.split("|")]
            if len(parts) < 7: continue
            name = parts[2]; dec = parts[3]
            cols = [c.strip() for c in parts[4].split(",") if c.strip()]
            if dec.startswith("✅") or dec.startswith("🔶") or (not dec.startswith("❌") and cols):
                flat[name] = cols
    return flat

def load_keys(path):
    d = {}
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if "|" not in ln: continue
            tbl, _, key = ln.partition("|")
            d.setdefault(tbl.strip(), set()).add(key.strip())
    return d

def to_camel(s):
    p = s.split("_")
    return p[0] + "".join(x.capitalize() for x in p[1:])

# 候选映射: (doc_key, 置信度, 理由). None doc_key = doc 无对应字段, 留空
M = {
 "admin_accounts": {
    "login_name": ("username", "高", "登录名对应 username"),
    "name": ("display_name", "中", "display_name 为显示名; 也可能指 role_name, 待确认"),
    "password_algorithm": (None, "-", "doc 仅有 password_hash/password_salt, 无算法字段, 留空"),
    "avatar_url": (None, "-", "doc 无头像字段, 留空"),
    "failed_login_count": (None, "-", "doc 无, 留空"),
    "locked_at": (None, "-", "doc 无(有 is_protected), 留空"),
    "last_login_ip": (None, "-", "doc 无, 留空"),
    "mfa_enabled": (None, "-", "doc 无 mfa 字段(有 is_protected 但语义不同), 留空"),
 },
 "admin_account_groups": {
    "parent_id": (None, "-", "doc 无 parent 字段, 留空"),
    "sort_order": (None, "-", "doc 无, 留空"),
 },
 "admin_model_instances": {
    "model_key": ("model_name", "中", "model_name 为模型标识"),
    "label": ("display_name", "高", "display_name 即显示标签"),
    "auth_type": (None, "-", "doc 无 auth_type(有 api_key/secret), 留空"),
    "sort_order": ("priority", "中", "priority 即优先级/排序"),
 },
 "admin_model_providers": {
    "base_url": ("default_base_url", "高", "default_base_url 即默认地址"),
    "api_key_encrypted": (None, "-", "doc 无 provider 级 api key, 留空"),
    "is_default": (None, "-", "doc 无 is_default, 留空"),
    "sort_order": ("priority", "中", "priority 即排序"),
 },
 "agent_kernel_bindings": {
    "kernel_type": ("kernel", "中", "kernel 为内核类型"),
    "kernel_id": ("kernel_session_id", "中", "kernel_session_id 为内核会话"),
    "binding_type": (None, "-", "doc 无明确绑定类型, 留空"),
    "binding_ref": ("source_ref", "中", "source_ref 为源引用"),
 },
 "autonomy_matrix": {
    "name": (None, "-", "doc 仅 cell/risk/level/decision, 结构完全不同, 留空"),
    "description": (None, "-", "同上, 留空"),
    "scope_type": (None, "-", "同上, 留空"),
    "scope_ref": (None, "-", "同上, 留空"),
    "rules": (None, "-", "同上, 留空"),
    "enabled": (None, "-", "同上, 留空"),
 },
 "chat_messages": {
    "sender_type": ("role", "高", "role 即发送者角色 user/assistant"),
    "sender_id": ("user_id", "中", "user_id 为发送者(另有 runtime_owner)"),
    "content_type": (None, "-", "doc 无 type(仅 content), 留空"),
    "status": (None, "-", "doc 无, 留空"),
    "parent_id": (None, "-", "doc 无父消息引用, 留空"),
    "reply_to_id": (None, "-", "doc 无, 留空"),
 },
 "chat_sessions": {
    "type": (None, "-", "doc 无 type, 留空"),
    "owner_user_id": ("user_id", "高", "user_id 即属主"),
    "participant_ids": (None, "-", "doc 无参与者列表, 留空"),
    "status": (None, "-", "doc 无, 留空"),
    "last_message_id": (None, "-", "doc 无消息ID列表, 留空"),
 },
 "end_user_org_relations": {
    "position_id": (None, "-", "doc 仅 org_id/user_id/is_primary, 无 position, 留空"),
    "role_type": (None, "-", "doc 无, 留空"),
    "status": (None, "-", "doc 无(有 is_primary), 留空"),
    "start_date": (None, "-", "doc 无, 留空"),
    "end_date": (None, "-", "doc 无, 留空"),
 },
 "end_user_position_roles": {
    "position_id": ("role_id", "中", "role_id 即角色标识(可能对应 position)"),
    "role_name": (None, "-", "doc 仅有 role_id, 无 name, 留空"),
    "role_type": (None, "-", "doc 无, 留空"),
    "status": (None, "-", "doc 无, 留空"),
    "start_date": (None, "-", "doc 无, 留空"),
    "end_date": (None, "-", "doc 无, 留空"),
 },
 "end_users": {
    "display_name": ("name", "高", "name 即用户显示名"),
    "phone": ("mobile", "高", "mobile 即手机号"),
    "avatar_url": (None, "-", "doc 无, 留空"),
    "password_algorithm": (None, "-", "doc 无, 留空"),
    "failed_login_count": (None, "-", "doc 无, 留空"),
    "locked_at": (None, "-", "doc 无, 留空"),
    "last_login_ip": (None, "-", "doc 无, 留空"),
    "mfa_enabled": (None, "-", "doc 无, 留空"),
 },
 "external_search_configs": {
    "name": ("provider", "中", "provider 为供应商名; 也可能需新字段, 待确认"),
    "api_key_encrypted": (None, "-", "doc 中 key 在 config 内, 平铺列取不到, 留空"),
    "endpoint": (None, "-", "endpoint 在 config 内, 留空"),
    "status": ("enabled", "低", "enabled 表示启用; 与 status 语义接近但不同, 待确认"),
    "sort_order": ("priority", "中", "priority 即排序"),
 },
 "gatekeeper_rules": {
    "name": (None, "-", "doc 仅 kind/mode 等, 结构不同, 留空"),
    "description": (None, "-", "同上, 留空"),
    "rule_type": (None, "-", "同上, 留空"),
    "condition": (None, "-", "同上, 留空"),
    "action": (None, "-", "同上, 留空"),
    "priority": (None, "-", "同上, 留空"),
    "enabled": (None, "-", "同上, 留空"),
 },
 "org_quota_policies": {
    "org_id": (None, "-", "doc 仅 tenant_id, 无 org_id, 留空"),
    "quota_type": (None, "-", "doc 无, 留空"),
    "quota_limit": ("total_tokens", "中", "total_tokens 即配额总量"),
    "quota_unit": (None, "-", "doc 无, 留空"),
 },
 "org_units": {
    "type": (None, "-", "doc 无, 留空"),
    "sort_order": (None, "-", "doc 无, 留空"),
    "leader_user_id": (None, "-", "doc 无, 留空"),
    "description": (None, "-", "doc 无, 留空"),
 },
 "organizations": {
    "name": ("org_name", "高", "org_name 即组织名"),
    "parent_id": (None, "-", "doc 无, 留空"),
    "path_ids": (None, "-", "doc 无, 留空"),
    "path_names": (None, "-", "doc 无, 留空"),
    "type": (None, "-", "doc 无, 留空"),
    "status": (None, "-", "doc 无(有 edition/tier), 留空"),
    "sort_order": (None, "-", "doc 无, 留空"),
    "description": (None, "-", "doc 无, 留空"),
    "contact_email": (None, "-", "doc 无, 留空"),
    "contact_phone": (None, "-", "doc 无, 留空"),
    "address": (None, "-", "doc 无, 留空"),
    "logo_url": (None, "-", "doc 无, 留空"),
    "settings": (None, "-", "doc 无, 留空"),
 },
 "pii_policies": {
    "name": ("pii_type", "中", "pii_type 即策略类型名"),
    "description": (None, "-", "doc 无, 留空"),
    "rules": ("strategy", "中", "strategy 即规则策略"),
    "enabled": (None, "-", "doc 无, 留空"),
 },
 "position_roles": {
    "type": (None, "-", "doc 无, 留空"),
    "level": (None, "-", "doc 无, 留空"),
    "sort_order": (None, "-", "doc 无, 留空"),
 },
 "skills": {
    "status": ("is_active", "低", "is_active(bool) 近似 status; 类型 TEXT 列需 CAST, 待确认"),
    "version": ("package_version", "高", "package_version 即版本号"),
    "data": ("config", "中", "config(JSONB) 近似 data(JSONB)"),
 },
 "tenants": {
    "description": (None, "-", "doc 无, 留空"),
    "contact_email": (None, "-", "doc 无, 留空"),
    "contact_phone": (None, "-", "doc 无, 留空"),
    "address": (None, "-", "doc 无, 留空"),
    "logo_url": (None, "-", "doc 无, 留空"),
    "settings": (None, "-", "doc 无, 留空"),
 },
}

def main():
    flat = parse_flat(DOC)
    keys = load_keys("/tmp/migration/keys.txt")
    md = ["# 候选 doc_key → column 映射表 (待确认)\n"]
    md.append("生成依据: 各表 doc 实际 key (keys.txt) + 语义推断。置信度: 高/中/低; '-' = doc 无对应字段, 建议留空。\n")
    fix_sql = ["-- 03b 修正回填: 仅高/中置信度映射列 (待用户确认后执行)\n"]
    n_map = 0
    for tbl, cols in flat.items():
        kset = keys.get(tbl, set())
        if not kset:
            continue
        missing = [c for c in cols if c not in BASE and c not in kset and to_camel(c) not in kset]
        if not missing:
            continue
        md.append(f"\n## {tbl}\n")
        md.append("| 列名 | 建议 doc_key | 置信度 | 理由 |\n|------|-------------|--------|------|")
        for c in missing:
            ent = M.get(tbl, {}).get(c)
            if ent:
                dk, conf, reason = ent
                md.append(f"| {c} | {dk} | {conf} | {reason} |")
                # 仅高/中 生成回填 SQL
                if conf in ("高", "中"):
                    typ = infer_type(c)
                    if typ == "JSONB":
                        fix_sql.append(
                            f"UPDATE {SCHEMA}.{tbl} SET {c} = doc->'{dk}' WHERE doc->'{dk}' IS NOT NULL;")
                    else:
                        fix_sql.append(
                            f"UPDATE {SCHEMA}.{tbl} SET {c} = CAST(doc->>'{dk}' AS {typ}) "
                            f"WHERE doc->>'{dk}' IS NOT NULL;")
                    n_map += 1
            else:
                md.append(f"| {c} | (留空) | - | doc 无对应字段 |")
    with open("/tmp/migration/candidate_mapping.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open("/tmp/migration/03b_backfill_fix.sql", "w", encoding="utf-8") as f:
        f.write("\n".join(fix_sql) + "\n")
    print(f"[gen_fix] 候选映射表已写 candidate_mapping.md; 高/中置信度回填语句: {n_map} 条 -> 03b_backfill_fix.sql")

if __name__ == "__main__":
    main()
