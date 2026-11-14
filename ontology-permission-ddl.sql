-- ============================================================================
-- 本体权限管理 —— 表结构设计稿（评审用）
--
-- 状态：**尚未落库**。定稿后移到 server/src/main/resources/db/migration/V4__ontology_permission.sql，
--       Flyway 会在下次后端启动时自动执行。
-- 配套：页面设计稿 docs/ontology-permission-mockup.html
--
-- 说明：主体（租户 / 组织 / 角色 / 用户）全部是墨攻（MOGO）里的 id，本平台不复制
--       一份过来，这里只存「谁 → 哪个本体 / 哪个类 → 什么级别、哪些列、哪些行」。
--
-- 授权维度（规范）：
--   · 本体级 = 授权 —— 能不能进这个本体（表 mesc_ontology_grant）
--   · 类级   = 明细 —— 该层授权之下的效果、列、行（表 mesc_ontology_class_detail）
--   · 类的粒度：**一个类只指向一张表，但一张表可以承载多个类** —— 类本质是这张表的
--     「列分组视图」（实测 customer-portrait：13 个类，11 个共用 ta_m_kpi_pers_
--     smartassessment_user，2 个共用 tw_d_evnt_cc_reco_file_role_cole）。所以类是最小
--     授权粒度，**物理表名不入库**，由 doc_blob['ontology-map'] 在读取时解析
--     （映射改了，规则跟着走，不会留存快照）。
--     连带两条约束：① 类的「列范围」天然是表列的子集（Customer 15 列 / 表 127 列），
--     界面上要显示的是**该类的列数**，不是表的列数；
--     ② row_condition / column_list 里的字段必须属于**该类**的列表，不能引同表其他类的列。
--   · 组织取主体时含下级，不展开存多行 —— 展开发生在读取时，按墨攻的 org_units 树。
--   · subject_type = 'tenant' 时，subject_id 存租户键本身（如 bonc-46057246211f3550f337c6f9），
--     与上面 tenant_id 列同值 —— 这样「整套只看一个租户」的兜底规则有个明确落点。
-- ============================================================================

-- 主体类型 subject_type：'tenant' | 'org' | 'role' | 'user'（两张表共用同一套取值）

-- ── 本体授权：给不给这个本体 ────────────────────────────────────────────────
CREATE TABLE mesc_ontology_grant (
    tenant_id    text        NOT NULL,
    subject_type text        NOT NULL CHECK (subject_type IN ('tenant','org','role','user')),
    subject_id   text        NOT NULL,
    ontology_uri text        NOT NULL,          -- doc_blob['ontology-map'].ontology 原文
    access_mode  text        NOT NULL CHECK (access_mode IN ('none','read','write')),
    priority     int         NOT NULL DEFAULT 100,   -- 同层冲突时数字大的胜出
    enabled      smallint    NOT NULL DEFAULT 1,     -- 0/1；A/B 兼容格式通用（对齐目标 public）
    remark       text,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_type, subject_id, ontology_uri)
);
-- 判权主路径：某主体在一个本体上有什么授权
CREATE INDEX ix_mesc_ontology_grant_subject ON mesc_ontology_grant (tenant_id, subject_type, subject_id);
CREATE INDEX ix_mesc_ontology_grant_onto    ON mesc_ontology_grant (tenant_id, ontology_uri);

-- ── 类明细：本体授权之下的细化 ──────────────────────────────────────────────
-- 可以只有明细、没有本体授权（明细压过本体）。明细没写就是「跟随本体」。
CREATE TABLE mesc_ontology_class_detail (
    tenant_id     text        NOT NULL,
    subject_type  text        NOT NULL CHECK (subject_type IN ('tenant','org','role','user')),
    subject_id    text        NOT NULL,
    ontology_uri  text        NOT NULL,
    class_name    text        NOT NULL,         -- doc_blob['ontology-map'].classes[].name 原文，如 'Customer'
    access_mode   text        NOT NULL DEFAULT 'inherit'
                              CHECK (access_mode IN ('inherit','none','read','write')),  -- inherit = 跟随本体
    column_mode   text        NOT NULL DEFAULT 'all' CHECK (column_mode IN ('all','selected')),
    column_list   jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- column_mode='selected' 时的列名数组
    row_condition jsonb,                        -- 行过滤条件树（含括号组与 ${user.*} 等主体变量）；NULL = 不过滤
    priority      int         NOT NULL DEFAULT 100,
    enabled       smallint    NOT NULL DEFAULT 1,    -- 0/1；A/B 兼容格式通用（对齐目标 public）
    remark        text,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_type, subject_id, ontology_uri, class_name)
);
CREATE INDEX ix_mesc_oclass_detail_subject ON mesc_ontology_class_detail (tenant_id, subject_type, subject_id);
-- 判权主路径：某个类上都有谁的明细
CREATE INDEX ix_mesc_oclass_detail_onto    ON mesc_ontology_class_detail (tenant_id, ontology_uri, class_name);

-- ── 权限变更审计 ────────────────────────────────────────────────────────────
CREATE TABLE mesc_ontology_perm_audit (
    id          bigserial   PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    tenant_id   text,
    actor       text,
    action      text        NOT NULL,   -- grant_save | grant_delete | detail_save | detail_delete | enforce_toggle
    target_kind text        NOT NULL,   -- grant | detail | config
    target_key  text,                   -- 主键各段拼起来，便于按对象翻历史
    detail      jsonb
);
CREATE INDEX ix_mesc_operm_audit_ts     ON mesc_ontology_perm_audit (ts DESC);
CREATE INDEX ix_mesc_operm_audit_target ON mesc_ontology_perm_audit (target_key, ts DESC);

-- ── 全局开关：复用已有的 sys_config，不另建表 ───────────────────────────────
-- key = 'ontology-permission'，value 形如：
--   { "enforce": false,          -- false = 只配置与预演，不拦实际查询（页头那条黄条）
--     "defaultMode": "allow" }   -- 未配置主体：'allow'（未受控）| 'deny'（白名单）
-- 键不存在时按上面这份默认值走，示例数据里给了一条显式写入（便于评审时看形状）。


-- ============================================================================
-- 示例数据（评审用）
--
-- 主体 id **全部取自本机墨攻 mogo_dev 的真实文档**，所以拔掉注释就能直接跑：
--   tenant  bonc-46057246211f3550f337c6f9       （organizations._id = 6acc8d65eafe3226ca19b05c）
--   org     6acc8d65eafe3226ca19b058            企业总部（当前无下级）
--   user    6accabae5a68ad8cef4d28bf            李博强 / liboqiang
--   role    system:bonc-46057246211f3550f337c6f9:full_access_admin   全能力管理员（内置）
--
-- ⚠ 本机墨攻目前**只有这 1 个用户、1 个组织、1 个角色**（后面两条 relation 里还有一个
--   user_id 6acc8d655a68ad8cef4d28ba，但 end_users 里查不到，是悬空数据）。
--   想完整演示「角色继承」「按组织树继承」，得先去墨攻管理端建下级组织和业务角色。
-- ============================================================================


-- ── 1. 租户兜底：本租户对客户画像本体只读，优先级压低 ────────────────────────
INSERT INTO mesc_ontology_grant
    (tenant_id, subject_type, subject_id, ontology_uri, access_mode, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'tenant', 'bonc-46057246211f3550f337c6f9',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'read', 10, 1,
     '租户级兜底，优先级低于下面的组织/用户规则')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri) DO UPDATE
   SET access_mode = EXCLUDED.access_mode,
       priority    = EXCLUDED.priority,
       enabled     = EXCLUDED.enabled,
       remark      = EXCLUDED.remark,
       updated_at  = now();

-- ── 2. 组织级授权：企业总部可以进这个本体（含将来它的下级）────────────────────
INSERT INTO mesc_ontology_grant
    (tenant_id, subject_type, subject_id, ontology_uri, access_mode, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'org', '6acc8d65eafe3226ca19b058',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'read', 100, 1,
     '业务只看不写')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri) DO UPDATE
   SET access_mode = EXCLUDED.access_mode,
       priority    = EXCLUDED.priority,
       enabled     = EXCLUDED.enabled,
       remark      = EXCLUDED.remark,
       updated_at  = now();

-- ── 3. 类明细：跟随本体 + 指定列 + 行过滤 ──────────────────────────────────
-- 李博强看 Customer 类：效果跟随本体（=只读），列白名单里剔掉证件/号码类字段，
-- 行过滤只看上海和江苏。注意 row_condition 里的 prov_name 确实是 Customer 的列。
INSERT INTO mesc_ontology_class_detail
    (tenant_id, subject_type, subject_id, ontology_uri, class_name,
     access_mode, column_mode, column_list, row_condition, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'user', '6accabae5a68ad8cef4d28bf',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'Customer',
     'inherit', 'selected',
     '["user_id","id","brand_id","city_name","prov_id","prov_name","statis_ym","user_area_belo_id"]'::jsonb,
     '{"kind":"group","op":"AND","children":[{"kind":"cond","field":"prov_name","op":"in","src":"lit","value":["上海","江苏"]}]}'::jsonb,
     100, 1,
     '只看上海/江苏，且不含 msisdn_sensid / sm4_cipher_msisdn 等号码类字段')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri, class_name) DO UPDATE
   SET access_mode   = EXCLUDED.access_mode,
       column_mode   = EXCLUDED.column_mode,
       column_list   = EXCLUDED.column_list,
       row_condition = EXCLUDED.row_condition,
       priority      = EXCLUDED.priority,
       enabled       = EXCLUDED.enabled,
       remark        = EXCLUDED.remark,
       updated_at    = now();

-- ── 4. 类明细「显式 none」压过本体授权 ─────────────────────────────────────
-- 同一个用户，本体上是只读，但 MarketingTouch（营销与触达）这一组字段显式关掉。
-- 这条就是 HTML 稿里「明细里显式写的 无/只读/读写 直接压过本体」的落点。
INSERT INTO mesc_ontology_class_detail
    (tenant_id, subject_type, subject_id, ontology_uri, class_name,
     access_mode, column_mode, column_list, row_condition, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'user', '6accabae5a68ad8cef4d28bf',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'MarketingTouch',
     'none', 'all', '[]'::jsonb, NULL, 100, 1,
     '营销触达字段不开放 —— 显式 none，压过上面的本体只读')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri, class_name) DO UPDATE
   SET access_mode   = EXCLUDED.access_mode,
       column_mode   = EXCLUDED.column_mode,
       column_list   = EXCLUDED.column_list,
       row_condition = EXCLUDED.row_condition,
       priority      = EXCLUDED.priority,
       enabled       = EXCLUDED.enabled,
       remark        = EXCLUDED.remark,
       updated_at    = now();

-- ── 5. 角色级明细：内置管理员也不豁免 ──────────────────────────────────────
-- 另一张表上的类。ContactSession 17 列里只放 6 个非号码字段，行过滤不设。
INSERT INTO mesc_ontology_class_detail
    (tenant_id, subject_type, subject_id, ontology_uri, class_name,
     access_mode, column_mode, column_list, row_condition, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'role',
     'system:bonc-46057246211f3550f337c6f9:full_access_admin',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'ContactSession',
     'inherit', 'selected',
     '["session_id","id","user_id","call_begin_tm","call_type_code","contat_chnl_name"]'::jsonb,
     NULL, 100, 1,
     '通话号码类字段（calling_phone / called_phone / acpt_phone 及各自 *_sensid）一律排除')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri, class_name) DO UPDATE
   SET access_mode   = EXCLUDED.access_mode,
       column_mode   = EXCLUDED.column_mode,
       column_list   = EXCLUDED.column_list,
       row_condition = EXCLUDED.row_condition,
       priority      = EXCLUDED.priority,
       enabled       = EXCLUDED.enabled,
       remark        = EXCLUDED.remark,
       updated_at    = now();

-- ── 6. 主体变量示例 —— 语法对、**语义目前不成立**，故意 enabled = false ────────
-- ⚠ 这是一个必须先说清的能力缺口：
--   ${user.id} 展开成墨攻端用户的 ObjectId（6accabae5a68ad8cef4d28bf），
--   而 Customer.user_id 是**业务侧的客户 id**，两者不同域，条件恒不成立。
--   HTML 稿里那个「只看本人数据」的快捷预设，要真能用，得先有一张
--   「端用户 → 业务主体」的属性映射（当前不存在，见 deploy/README.md 的能力边界）。
--   所以这条以草稿形态入库，评审时用来确认条件和开关的形状。
INSERT INTO mesc_ontology_class_detail
    (tenant_id, subject_type, subject_id, ontology_uri, class_name,
     access_mode, column_mode, column_list, row_condition, priority, enabled, remark)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'user', '6accabae5a68ad8cef4d28bf',
     'https://ecs.cmcc.local/ontology/customer-portrait#', 'ComplaintRecord',
     'inherit', 'all', '[]'::jsonb,
     '{"kind":"cond","field":"user_id","op":"=","src":"var","value":"${user.id}"}'::jsonb,
     100, 0,
     '草稿：等「端用户 → 业务列」映射建起来再启用')
ON CONFLICT (tenant_id, subject_type, subject_id, ontology_uri, class_name) DO UPDATE
   SET access_mode   = EXCLUDED.access_mode,
       column_mode   = EXCLUDED.column_mode,
       column_list   = EXCLUDED.column_list,
       row_condition = EXCLUDED.row_condition,
       priority      = EXCLUDED.priority,
       enabled       = EXCLUDED.enabled,
       remark        = EXCLUDED.remark,
       updated_at    = now();

-- ── 7. 全局开关 ────────────────────────────────────────────────────────────
INSERT INTO sys_config (key, value)
VALUES ('ontology-permission', '{"enforce": false, "defaultMode": "allow"}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- ── 8. 审计 ────────────────────────────────────────────────────────────────
-- target_key 约定：'<subject_type>/<subject_id>/<ontology_uri>/<class_name>'，
-- 本体级把最后一段留空；config 类直接用配置键。
INSERT INTO mesc_ontology_perm_audit
    (tenant_id, actor, action, target_kind, target_key, detail)
VALUES
    ('bonc-46057246211f3550f337c6f9', 'liboqiang', 'grant_save', 'grant',
     'org/6acc8d65eafe3226ca19b058/https://ecs.cmcc.local/ontology/customer-portrait#/',
     '{"access_mode":"read","priority":100}'::jsonb),
    ('bonc-46057246211f3550f337c6f9', 'liboqiang', 'detail_save', 'detail',
     'user/6accabae5a68ad8cef4d28bf/https://ecs.cmcc.local/ontology/customer-portrait#/Customer',
     '{"column_mode":"selected","column_count":8,"has_row_condition":true}'::jsonb),
    ('bonc-46057246211f3550f337c6f9', 'liboqiang', 'enforce_toggle', 'config',
     'ontology-permission',
     '{"enforce":false}'::jsonb);
