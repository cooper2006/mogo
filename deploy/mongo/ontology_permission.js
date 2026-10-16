// ============================================================================
// 本体权限 MongoDB 侧集合结构（合并方案产出）
//
// 对齐：deploy/pg/ontology_permission.sql（PanWeiDB / openGauss 侧）
// SDD 规约：specs/030-ontology-data-permission/
// 用途：mongo 后端（MOGO_DATA_BACKEND=mongo）下建立与 PanWeiDB 侧**等价**的集合、
//       字段约束（$jsonSchema）与索引，保障两种数据库行为一致。
// 用法：mongosh "<uri>/<db>" deploy/mongo/ontology_permission.js
//       （<db> 取 mongo 后端 settings.mongodb_db，默认与 .env 一致）
// 说明：脚本幂等 —— 集合不存在则建、已存在则 collMod 更新校验器；索引 createIndex 幂等。
//       **已于 2026-10-16 在 mogo_dev 执行**（4 个集合 + 9 个索引 + sys_config 种子）。
//
// ── 两种后端一致性映射（PG ↔ Mongo）────────────────────────────────────────
//   · PG 复合主键 → Mongo `_id` 由复合键**确定性拼接**（等价唯一，支持 upsert）。
//     grant : `${tenant_id}|${subject_type}|${subject_id}|${ontology_uri}`
//     detail: `${tenant_id}|${subject_type}|${subject_id}|${ontology_uri}|${class_name}`
//     audit : `_id` 自动 ObjectId（对应 PG 的 bigserial 代理键）
//     sys_config: `_id` = 配置键 key
//   · PG jsonb（column_list / row_condition）→ Mongo 原生数组 / 对象。
//   · PG timestamptz → Mongo Date（UTC）。
//   · PG CHECK 约束 → Mongo $jsonSchema 的 enum。
//   · PG 默认值（priority=100 / enabled=true / column_mode='all' / column_list=[]）
//     Mongo 无列默认值，由应用层写入时补齐（此处仅在 schema 注释标注）。
//
// ── ⚠ 兼容门面 caveat（"两种库都能用"的关键前提）────────────────────────────
//   mogo 的 pg_compat 门面（services/admin-api/app/core/pg_compat.py:11-13）假定每张表
//   都是通用壳 `(id TEXT PRIMARY KEY, tenant_id TEXT, doc JSONB NOT NULL, created_at,
//   updated_at)`：insert_one 走 `ON CONFLICT (id)`、upsert 自动补 `_id`、查询从 `doc`
//   JSONB 取字段。**本文件与 PG 段都是结构化列，不经该门面**。
//   因此应用层二选一：
//     (A) 原生 repository：PG 走 SQL、mongo 走 motor（本文件即为此路径的 mongo 侧）；
//     (B) 若要复用 pg_compat 门面：需把两侧改成通用壳 + 在 app/core/column_map.py 的
//         COLUMN_MAP 提升热字段（subject_type/subject_id/ontology_uri/class_name/enabled）
//         为真实列。两条路径不可混用。
// ============================================================================

const now = new Date();

function ensureCollection(name, jsonSchema) {
  const validator = {
    $jsonSchema: jsonSchema,
  };
  const opts = { validator, validationLevel: "strict", validationAction: "error" };
  if (!db.getCollectionNames().includes(name)) {
    db.createCollection(name, opts);
    print("[create] " + name);
  } else {
    db.runCommand(Object.assign({ collMod: name }, opts));
    print("[collMod] " + name);
  }
}

// ── 全局开关：sys_config（附带，PG 侧同表）──────────────────────────────────
ensureCollection("sys_config", {
  bsonType: "object",
  required: ["value"],
  properties: {
    _id: { bsonType: "string", description: "配置键，如 ontology-permission" },
    value: { bsonType: "object", description: "配置体，如 {enforce,defaultMode}" },
    created_at: { bsonType: "date" },
    updated_at: { bsonType: "date" },
  },
});
db.sys_config.createIndex({ updated_at: -1 }, { name: "sys_config_updated_idx" });

// ── 本体授权：给不给这个本体 ────────────────────────────────────────────────
ensureCollection("mesc_ontology_grant", {
  bsonType: "object",
  required: ["tenant_id", "subject_type", "subject_id", "ontology_uri", "access_mode"],
  properties: {
    _id: { bsonType: "string", description: "tenant_id|subject_type|subject_id|ontology_uri" },
    tenant_id: { bsonType: "string" },
    subject_type: { bsonType: "string", enum: ["tenant", "org", "role", "user"] },
    subject_id: { bsonType: "string" },
    ontology_uri: { bsonType: "string" },
    access_mode: { bsonType: "string", enum: ["none", "read", "write"] },
    priority: { bsonType: ["int", "long", "double"], description: "默认 100，大者胜" },
    enabled: { bsonType: "bool", description: "默认 true" },
    remark: { bsonType: ["string", "null"] },
    created_at: { bsonType: "date" },
    updated_at: { bsonType: "date" },
  },
});
// 判权主路径：某主体在一个本体上有什么授权
db.mesc_ontology_grant.createIndex(
  { tenant_id: 1, subject_type: 1, subject_id: 1 },
  { name: "mesc_ontology_grant_subject_idx" }
);
db.mesc_ontology_grant.createIndex(
  { tenant_id: 1, ontology_uri: 1 },
  { name: "mesc_ontology_grant_onto_idx" }
);

// ── 类明细：本体授权之下的细化 ──────────────────────────────────────────────
ensureCollection("mesc_ontology_class_detail", {
  bsonType: "object",
  required: ["tenant_id", "subject_type", "subject_id", "ontology_uri", "class_name"],
  properties: {
    _id: { bsonType: "string", description: "tenant_id|subject_type|subject_id|ontology_uri|class_name" },
    tenant_id: { bsonType: "string" },
    subject_type: { bsonType: "string", enum: ["tenant", "org", "role", "user"] },
    subject_id: { bsonType: "string" },
    ontology_uri: { bsonType: "string" },
    class_name: { bsonType: "string", description: "doc_blob['ontology-map'].classes[].name" },
    access_mode: { bsonType: "string", enum: ["inherit", "none", "read", "write"], description: "默认 inherit" },
    column_mode: { bsonType: "string", enum: ["all", "selected"], description: "默认 all" },
    column_list: { bsonType: "array", items: { bsonType: "string" }, description: "column_mode=selected 时的列名数组，默认 []" },
    row_condition: { bsonType: ["object", "null"], description: "行过滤条件树；null = 不过滤" },
    priority: { bsonType: ["int", "long", "double"], description: "默认 100" },
    enabled: { bsonType: "bool", description: "默认 true" },
    remark: { bsonType: ["string", "null"] },
    created_at: { bsonType: "date" },
    updated_at: { bsonType: "date" },
  },
});
// 判权主路径：某个类上都有谁的明细
db.mesc_ontology_class_detail.createIndex(
  { tenant_id: 1, subject_type: 1, subject_id: 1 },
  { name: "mesc_ontology_class_detail_subject_idx" }
);
db.mesc_ontology_class_detail.createIndex(
  { tenant_id: 1, ontology_uri: 1, class_name: 1 },
  { name: "mesc_ontology_class_detail_onto_idx" }
);

// ── 权限变更审计（配置变更走这里，运行时判定仍落 gate_events，不双写）─────────
ensureCollection("mesc_ontology_perm_audit", {
  bsonType: "object",
  required: ["action", "target_kind"],
  properties: {
    _id: { description: "自动 ObjectId（对应 PG bigserial）" },
    ts: { bsonType: "date", description: "默认 now()" },
    tenant_id: { bsonType: ["string", "null"] },
    actor: { bsonType: ["string", "null"] },
    action: {
      bsonType: "string",
      enum: ["grant_save", "grant_delete", "detail_save", "detail_delete", "enforce_toggle"],
    },
    target_kind: { bsonType: "string", enum: ["grant", "detail", "config"] },
    target_key: { bsonType: ["string", "null"], description: "<subject_type>/<subject_id>/<ontology_uri>/<class_name>" },
    detail: { bsonType: ["object", "null"] },
  },
});
db.mesc_ontology_perm_audit.createIndex({ ts: -1 }, { name: "mesc_ontology_perm_audit_ts_idx" });
db.mesc_ontology_perm_audit.createIndex(
  { target_key: 1, ts: -1 },
  { name: "mesc_ontology_perm_audit_target_idx" }
);

// ── 全局开关初始值（幂等，PG 侧同值）────────────────────────────────────────
db.sys_config.updateOne(
  { _id: "ontology-permission" },
  {
    $setOnInsert: {
      value: { enforce: false, defaultMode: "allow" },
      created_at: now,
    },
    $set: { updated_at: now },
  },
  { upsert: true }
);
print("[seed] sys_config/ontology-permission");

print("done: ontology_permission mongo structure ready");
