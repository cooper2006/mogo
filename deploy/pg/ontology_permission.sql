-- ============================================================================
-- 本体权限建表段（合并方案产出）
--
-- 配套设计：docs/ontology-permission-merge-plan.md（决策已定，**已落地**）
-- 原始设计稿：docs/ontology-permission-ddl.sql
-- SDD 规约：specs/030-ontology-data-permission/
--
-- 说明：
--   本文件是 deploy/pg 下的一份**独立建表段**，尚未并入 deploy/pg/schema.sql。
--   **已于 2026-10-16 在 mogo_dev 执行入库**（sys_config + 3 张 mesc_*）。
--   脚本幂等（CREATE TABLE/INDEX IF NOT EXISTS + ON CONFLICT DO NOTHING），可重复执行。
--   后续若要并入 schema.sql（由 scripts/pg/generate_ddl.py 一并生成），需注意
--   本段是**结构化列**，与生成器的通用壳 `(id, tenant_id, doc JSONB, ...)` 不兼容。
--
-- 与 PanWeiDB（openGauss 内核，sql_compatibility=A）兼容要点：
--   · 列均为结构化列 + 部分 jsonb（column_list / row_condition），不使用通用 doc JSONB 壳。
--   · CHECK 约束 / 复合主键 / jsonb 类型 / now() 均受支持；查询期的 A 模式坑
--     （''=NULL、NOT(@>) 求值错误用 IS NOT TRUE、jsonb 走 #>/#>>、占位符顺序）
--     属于应用层判权逻辑，不在本 DDL 范围。
--
-- 已落定的三项决策（见 merge-plan §5）：
--   ① sys_config 新建通用配置表（非复用）；
--   ② 本体数据权限层为**独立可选**执行层，由 sys_config['ontology-permission'].enforce
--      控制是否真正拦截，不依赖 RBAC kg:read；
--   ③ enforce=true 时未匹配主体缺省 **deny**（fail-closed）；defaultMode 仅用于
--      enforce=false 的预演/展示口径。
--
-- 两种后端一致性（对应 mongo 侧 deploy/mongo/ontology_permission.js）：
--   · 本段为**结构化列**，与 mongo 集合字段一一对应（jsonb ↔ 数组/对象、timestamptz ↔ Date、
--     CHECK ↔ $jsonSchema.enum）；mongo 侧 `_id` 由复合键确定性拼接，等价于此处的复合主键。
--   · ⚠ 兼容门面 caveat：pg_compat（app/core/pg_compat.py:11-13）假定通用壳
--     `(id, tenant_id, doc JSONB, created_at, updated_at)`。本结构化表**不经该门面**，
--     应用层须走原生 repository（PG SQL / mongo motor）；若要走门面，两侧都要改壳式 +
--     在 app/core/column_map.py 的 COLUMN_MAP 提升热字段。两条路径不可混用。
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS "mogo_dev";

-- ── 全局开关：新建通用配置表（决策①）────────────────────────────────────────
-- key = 配置键（如 'ontology-permission'），value = jsonb 配置体。
-- 原 DDL 注释"复用已有的 sys_config"，但仓库内本无此表，故此处新建。
CREATE TABLE IF NOT EXISTS "mogo_dev"."sys_config" (
    key         TEXT        PRIMARY KEY,
    value       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 本体权限开关初始值：enforce=false（只配置预演、不拦查询）。
-- 注意：defaultMode 在 enforce=false 时仅作预演口径；enforce=true 后实际缺省为 deny（决策③）。
INSERT INTO "mogo_dev"."sys_config" (key, value)
VALUES ('ontology-permission', '{"enforce": false, "defaultMode": "allow"}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- ── 本体授权：给不给这个本体 ────────────────────────────────────────────────
-- 本体数据权限层为独立可选执行层（决策②），不强制先过 RBAC kg:read。
CREATE TABLE IF NOT EXISTS "mogo_dev"."mesc_ontology_grant" (
    tenant_id    TEXT        NOT NULL,
    subject_type TEXT        NOT NULL CHECK (subject_type IN ('tenant','org','role','user')),
    subject_id   TEXT        NOT NULL,
    ontology_uri TEXT        NOT NULL,          -- doc_blob['ontology-map'].ontology 原文
    access_mode  TEXT        NOT NULL CHECK (access_mode IN ('none','read','write')),
    priority     INT         NOT NULL DEFAULT 100,   -- 同层冲突时数字大的胜出
    enabled      SMALLINT    NOT NULL DEFAULT 1,     -- 0/1；A/B 兼容格式通用（对齐目标 public 的 smallint）
    remark       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 与仓库其他表一致，设计稿未列但建议保留
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_type, subject_id, ontology_uri)
);

-- 判权主路径：某主体在一个本体上有什么授权
CREATE INDEX IF NOT EXISTS "mesc_ontology_grant_subject_idx"
    ON "mogo_dev"."mesc_ontology_grant" (tenant_id, subject_type, subject_id);
CREATE INDEX IF NOT EXISTS "mesc_ontology_grant_onto_idx"
    ON "mogo_dev"."mesc_ontology_grant" (tenant_id, ontology_uri);

-- ── 类明细：本体授权之下的细化 ──────────────────────────────────────────────
-- 可以只有明细、没有本体授权（明细压过本体）。明细没写就是「跟随本体」。
-- 物理表名不入库：类本质是某张表的「列分组视图」，由 doc_blob['ontology-map']
-- 在读取时解析（映射改了规则跟着走，不留快照）。
CREATE TABLE IF NOT EXISTS "mogo_dev"."mesc_ontology_class_detail" (
    tenant_id     TEXT        NOT NULL,
    subject_type  TEXT        NOT NULL CHECK (subject_type IN ('tenant','org','role','user')),
    subject_id    TEXT        NOT NULL,
    ontology_uri  TEXT        NOT NULL,
    class_name    TEXT        NOT NULL,         -- doc_blob['ontology-map'].classes[].name 原文，如 'Customer'
    access_mode   TEXT        NOT NULL DEFAULT 'inherit'
                               CHECK (access_mode IN ('inherit','none','read','write')),  -- inherit = 跟随本体
    column_mode   TEXT        NOT NULL DEFAULT 'all' CHECK (column_mode IN ('all','selected')),
    column_list   JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- column_mode='selected' 时的列名数组
    row_condition JSONB,                        -- 行过滤条件树；NULL = 不过滤
    priority      INT         NOT NULL DEFAULT 100,
    enabled       SMALLINT    NOT NULL DEFAULT 1,    -- 0/1；A/B 兼容格式通用（对齐目标 public 的 smallint）
    remark        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_type, subject_id, ontology_uri, class_name)
);

-- 判权主路径：某个类上都有谁的明细
CREATE INDEX IF NOT EXISTS "mesc_ontology_class_detail_subject_idx"
    ON "mogo_dev"."mesc_ontology_class_detail" (tenant_id, subject_type, subject_id);
CREATE INDEX IF NOT EXISTS "mesc_ontology_class_detail_onto_idx"
    ON "mogo_dev"."mesc_ontology_class_detail" (tenant_id, ontology_uri, class_name);

-- ── 权限变更审计（配置变更走这里，运行时判定仍落 gate_events，不双写）─────────
CREATE TABLE IF NOT EXISTS "mogo_dev"."mesc_ontology_perm_audit" (
    id           BIGSERIAL   PRIMARY KEY,   -- A 格式：不支持 AUTO_INCREMENT，用序列等价实现
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id    TEXT,
    actor        TEXT,
    action       TEXT        NOT NULL,   -- grant_save | grant_delete | detail_save | detail_delete | enforce_toggle
    target_kind  TEXT        NOT NULL,   -- grant | detail | config
    target_key   TEXT,                   -- 主键各段拼起来，便于按对象翻历史
    detail       JSONB
);

CREATE INDEX IF NOT EXISTS "mesc_ontology_perm_audit_ts_idx"
    ON "mogo_dev"."mesc_ontology_perm_audit" (ts DESC);
CREATE INDEX IF NOT EXISTS "mesc_ontology_perm_audit_target_idx"
    ON "mogo_dev"."mesc_ontology_perm_audit" (target_key, ts DESC);

-- ============================================================================
-- 增量迁移：``enabled`` 布尔 → SMALLINT(1/0)
-- ----------------------------------------------------------------------------
-- 背景：目标库（B 格式，``public`` schema）里 ``mesc_ontology_grant`` /
-- ``mesc_ontology_class_detail`` 的 ``enabled`` 是 ``SMALLINT DEFAULT 1``；本库
-- （A 格式，``mogo_dev`` schema）此前是 ``BOOLEAN DEFAULT true``。两者语义同为
-- 「启用/禁用」，但物理类型不一致，跨库对齐后判权热路径不再依赖布尔字面量。
--
-- 本段可重复执行（幂等）：`CASE WHEN enabled THEN 1 ELSE 0 END` 对 bool 与
-- SMALLINT 两种输入都成立；``SET DEFAULT 1`` 重复执行无副作用。
-- ============================================================================
ALTER TABLE "mogo_dev"."mesc_ontology_grant"
    ALTER COLUMN enabled TYPE SMALLINT
    USING (CASE WHEN enabled THEN 1 ELSE 0 END);
ALTER TABLE "mogo_dev"."mesc_ontology_grant"
    ALTER COLUMN enabled SET DEFAULT 1;

ALTER TABLE "mogo_dev"."mesc_ontology_class_detail"
    ALTER COLUMN enabled TYPE SMALLINT
    USING (CASE WHEN enabled THEN 1 ELSE 0 END);
ALTER TABLE "mogo_dev"."mesc_ontology_class_detail"
    ALTER COLUMN enabled SET DEFAULT 1;

-- 审计表自增 id：A 格式（openGauss/PG 兼容）**不支持** ``AUTO_INCREMENT``
-- （实测 ``ERROR: auto_increment is supported only in B-format database``），
-- 故保留 ``BIGSERIAL``（底层即 ``nextval('mogo_dev.mesc_ontology_perm_audit_id_seq')``）。
-- B 格式目标库用 ``AUTO_INCREMENT`` 只是同一「自增主键」语义的另一种语法；
-- 后端 ``INSERT`` 从不写 ``id`` 列（见 ``repository.py::write_audit``），故两侧行为等价。

-- ============================================================================
-- 示例数据（评审用，原稿见 docs/ontology-permission-ddl.sql:104-247）
-- 主体 id 取自本机 mogo_dev 真实文档，核对设计稿后可取消注释执行。
-- 其中 ComplaintRecord 那条 ${user.id} 主体变量语义不成立（端用户 ObjectId ≠ 业务
-- customer id），在设计稿里 enabled=false，启用前需先建「端用户→业务主体」映射表。
-- （此处不展开，避免与 schema 生成耦合；评审阶段直接参考原 DDL 示例段即可。）
-- ============================================================================
