# 本体权限架构合并方案（评审稿）

> **文档类型**：架构评审稿 / 合并方案
> **状态**：🟢 **已落地（2026-10-16）** —— 建表入库 + 运行时解析 + 管理端 API/前端均已实现；
> SDD 规约见 `specs/030-ontology-data-permission/`（回溯补规格）
> **基线**：`docs/ontology-permission-ddl.sql`（设计稿）+ 仓库当前 `deploy/pg/schema.sql` 与 `services/admin-api/app/governance/*` 权限体系
> **撰写日期**：2026-10-16
> **事实来源**：结论以代码与 DDL 为准，关键论断标注 `文件:行号`

## 落地状态（2026-10-16）

| 层 | 产出 | 状态 |
|---|---|---|
| 建表（PanWeiDB） | `deploy/pg/ontology_permission.sql` → `mogo_dev` 建出 `sys_config` + 3 张 `mesc_*` | ✅ 已执行 |
| 建表（MongoDB） | `deploy/mongo/ontology_permission.js` → `mogo_dev` 建出 4 集合 + 9 索引 | ✅ 已执行 |
| 运行时解析（chat-api） | `app/services/ontology_permission.py`（fail-closed + 60s 缓存 + gate_events 审计） | ✅ 已落地（11 条测试） |
| 检索生效点（chat-api） | `app/services/business_semantic_index.py` 按 `ontology_id` 过滤 | ✅ 已落地（6 条测试） |
| 管理端（admin-api） | `app/ontology_permission/` 原生 repository + 服务层；`routes/ontologies.py`（13 路由）+ `routes/ontology_permission_internal.py` | ✅ 已落地（20 条测试） |
| 管理端（admin-web） | `/ontologies` 清单页 + 用户授权弹窗 + 用户管理入口 | ✅ 已落地（待构建验证） |

> **未闭环项**（详见 `specs/030-ontology-data-permission/tasks.md` 末节）：
> ① 索引写入方暂不填真实 `ontology_id`（业务系统集成后再接入）；
> ② `sourceEntity`/`keyField` 暂为空串（设计 §5.4 的独立副本集合属阶段 4）；
> ③ 类明细（列投影 / 行过滤）已建表与提供仓储，但**尚未接进检索生效点**；
> ④ 跨进程缓存传播窗口 = 60s TTL 上限（两服务均未引入 Redis 客户端）；
> ⑤ `/internal/*` 需在网关显式放行（设计 §6 约束 6）。

---

## 0. 一句话结论

`docs/ontology-permission-ddl.sql` 提出的 `mesc_*` 三表，**不是要替换现有 RBAC**，而是给**本体（ontology）域新增一层"数据范围（data scope）"权限**，与既有的"功能权限（能不能做这个动作）"**正交、互补**。合并原则：**本体数据权限层是独立、可选的执行层**，由 `sys_config['ontology-permission'].enforce` 开关控制是否真正拦截；它**不强制要求**先过 `kg:read` 等 RBAC 功能权限（两层正交、可各自独立开关）。`enforce=false` 时只配置与预演、不拦查询；`enforce=true` 时按 fail-closed 缺省 **deny**（见 §3.5 / §5）。后端策略采用 **(A) 原生 repository**（PG SQL / mongo motor，结构化列，不经 `pg_compat` 门面，见 §3.8）。

---

## 1. 背景：现有两套结构

### 1.1 现有表结构（`deploy/pg/schema.sql`）

- 全部业务表是**通用壳**：`(id TEXT PK, tenant_id TEXT, doc JSONB, created_at, updated_at)`，由 `scripts/pg/generate_ddl.py` 生成（文件头注释见 `deploy/pg/schema.sql:1-2`）。
- 与权限相关的表也走通用壳：`permission_grants`（`:528`）、`resource_grants`（`:645`）、`enterprise_session_approval_grants`（`:258`）。
- **没有 `sys_config` 表**（全仓库 grep 仅 `docs/ontology-permission-ddl.sql` 自身引用）。
- **没有 `mesc_*` 任何表**，也没有 Flyway 迁移机制。

### 1.2 现有权限体系（功能权限维度）

- 权限码 `<resource>:<action>[:<target>]`，由 `permission_grants` 存显式授予，3 级隔离 `tenant/org/user`（`services/admin-api/app/governance/permission_grants.py:32,34`）。
- 角色是 `position_roles` 预设组，在 RBAC 层展开成权限码（`services/admin-api/app/governance/layers/rbac.py:17`）。
- 门禁六层：`identity → rbac → redaction → approval → quota → audit`（`deliverables/gstack/permission-control-data-scope-2026-10-08.md` 第 2 章）。
- 既有体系管"功能权限（action）"，**没有针对"本体/类/列/行"的数据范围层**。

---

## 2. 两层权限定位对照

| 维度 | 现有体系（功能权限） | 新本体权限（数据范围，DDL） |
|---|---|---|
| 管什么 | `<resource>:<action>[:<target>]` 权限码 | 哪个**本体 / 类 / 列 / 行**可见 |
| 落点 | `permission_grants` + `position_roles`，经 gatekeeper 第 2 层 rbac | `mesc_ontology_grant` / `mesc_ontology_class_detail` |
| 隔离级 | 3 级：tenant / org / user | 4 态：tenant / org / role / user |
| 审计 | `gate_events` + `system_audit_logs` | `mesc_ontology_perm_audit`（专用） |
| 开关 | 无统一开关 | `sys_config['ontology-permission'].enforce` |

```text
本体查询请求
   │
   ▼
① 功能权限 RBAC 判定        (现有层 · kg:read|write via permission_grants + position_roles)
   │  deny → 拦截
   ▼
② 本体数据权限层 mesc_*      (新层 · 本体授权 + 类明细 + 列/行过滤)
   │  sys_config.enforce=false 时仅预演、不拦截
   ▼
③ 数据范围解析              (doc_blob['ontology-map'] 把 类 → 物理表)
   ▼
④ 数据读取                  (列投影 + 行过滤)
```

判权优先级（同层 `priority` 大者胜）：
`tenant 兜底行 → org(+下级,树展开) → role(position_roles展开) → user 自身`；
类级再覆盖：`inherit / none / read / write` + `column_list` 列子集 + `row_condition` 行过滤；
缺省：`defaultMode` = allow（未受控）/ deny（白名单）。

---

## 3. 合并方案（7 点）

### 3.1 表结构落点 —— 别套现有 doc-JSONB 壳

- **问题**：当前 `schema.sql` 所有表都是通用 JSONB 壳，且**没有 Flyway**。DDL 注释却写"定稿后移到 `server/src/main/resources/db/migration/V4__ontology_permission.sql`（Flyway）"（`:4-5`），本仓库是 Python + PanWeiDB + `generate_ddl.py`，栈不符。
- **做法**：把三张 `mesc_*` 表作为**独立段**加入 `deploy/pg/schema.sql`（或新建 `deploy/pg/ontology_permission.sql` 由 `generate_ddl.py` 合并）。表名带 `mogo_dev.` schema 前缀（与现有一致）。`mesc_*` 需要**结构化列**，不能用通用 `doc` JSONB 壳。

### 3.2 `sys_config` 缺口 —— 已定 (a) 新建通用配置表

- **问题**：DDL 说"复用已有的 `sys_config`"（`:83-87`），但全仓库无此表，`schema.sql` 里也不存在。
- **决定（2026-10-16）**：**(a) 新建 `sys_config(key text primary key, value jsonb)` 通用配置表**。顺带统一散落配置（如 `admin_presentation_settings`）。
- **DDL 形态**：`INSERT INTO sys_config (key, value) VALUES ('ontology-permission', '{"enforce": false, "defaultMode": "allow"}'::jsonb)`。键不存在时按 `{"enforce": false, "defaultMode": "allow"}` 走；但 `enforce=true` 时的实际缺省判定见 §3.5（固定 deny）。

### 3.3 与 `permission_grants` / RBAC 的关系（已定：本体层独立可选）

- **决定（2026-10-16）**：本体数据权限层是**独立、可选**的执行层，**不强制要求**先过 `kg:read` 等 RBAC 功能权限。两层正交互补、可各自独立开关；是否启用由 `sys_config['ontology-permission'].enforce` 控制。
- 把新本体层挂在**查询执行前的数据范围解析**位置（类似 redaction，但结构化、可配置），**不**塞进 gatekeeper 的 action 判定。
- RBAC 管"能不能做这个动作"，本体层管"看到哪些列/行"，二者解耦；业务上仍可在更上层另行叠加 `kg:read` 限制，但本体层本身不依赖它。
- 作用域先限定 `kg` / `ontology` 资源域，不要一上来对所有 `bizdata/knowledge` 表生效。

### 3.4 四态主体对齐

- 新 DDL 把 `role` 当一等主体（`subject_type='role'`，`subject_id` 用 `position_roles._id`，如 `system:<tenant>:full_access_admin`）。
- 现有 `permission_grants` 是 3 级、无 role 级（role 在 rbac 层展开成权限码）。
- **做法**：判权时把 user 的 `position_roles` 展开成 role 主体集合，再与 tenant/org/user 自身规则一起参与 resolution —— 与 `rbac.py` 的 `expand_role_to_codes` 同源，可复用角色展开逻辑。
- 组织含下级：按 `org_units` 树读取时展开。**待核**：`org_units` 表装的是墨攻组织树（DDL 注释假设，`:22`）还是 mogo 自己的——合并前需确认。

### 3.5 判权算法（resolution）

- 输入：subject 上下文（tenant_id + 展开出的 `[tenant, org(+下级), role*, user]`）+ `ontology_uri` + `class_name`。
- **本体级基调**：命中的 `mesc_ontology_grant` 行中取 `enabled=true` 且 `priority` 最大者的 `access_mode`；`subject_type='tenant'` 行即"整套只看一个租户"兜底（`:23`）。
- **类级覆盖**：对目标 class 取 `mesc_ontology_class_detail` 中 `priority` 最大行；`inherit` 沿用本体基调，`none/read/write` 覆盖；`column_mode='selected'` 套 `column_list` 列子集；`row_condition` 叠加（AND）。
- **缺省失败模式（已定，2026-10-16）**：`enforce=true` 时缺省 **deny**（fail-closed，贴合 mogo 既有基调）；`defaultMode` 配置项保留（值 `allow`/`deny`），但**开启 enforcement 后未匹配主体的实际判定固定为 deny**（白名单语义），`defaultMode` 仅用于 `enforce=false` 的展示/预演口径。

### 3.6 审计合并（不要双写）

- **配置变更**（grant/detail/config 增删改）→ 走 `mesc_ontology_perm_audit`（自带 `target_key`，便于按对象翻历史，与 DDL 一致）。
- **运行时判定** → 仍落 `gate_events`（与既有门禁审计统一）。同一事件不写两处。

### 3.7 灰度节奏（对应"不着急落地"）

DDL 已设计 `enforce` 开关（默认 false = 只配置预演、不拦查询），天然支持渐进：
- 阶段 0：表结构落库（`mesc_*` + `sys_config`），`enforce=false`，页面黄条提示；
- 阶段 1：管理端按 `docs/ontology-permission-mockup.html` 录入规则，纯预演；
- 阶段 2：单本体/单租户开 `enforce=true` 灰度，观察 `gate_events` 命中；
- 阶段 3：全量。

### 3.8 后端策略 —— 已定 (A) 原生 repository（结构化列，不走 pg_compat 门面）

- **背景**：mogo 双后端（mongo / PanWeiDB）经 `pg_compat` 门面统一，但该门面假定通用壳 `(id TEXT PK, tenant_id, doc JSONB, created_at, updated_at)`（`services/admin-api/app/core/pg_compat.py:11-13`，`insert_one` 走 `ON CONFLICT (id)`、upsert 自动补 `_id`）。
- **决定（2026-10-16）**：本体权限采用 **(A) 原生 repository** —— PG 走 SQL、mongo 走 motor；`mesc_*` 用**结构化列**，**不经** `pg_compat` 门面。
- **产出**：`deploy/pg/ontology_permission.sql`（PG 结构化建表段）+ `deploy/mongo/ontology_permission.js`（mongo 集合结构），字段一一对应。
- **已实现（2026-10-16）**：`services/admin-api/app/ontology_permission/repository.py` 提供双后端同形访问；upsert 在 PG 侧走「先 UPDATE、`rowcount=0` 再 INSERT」（规避 openGauss `ON CONFLICT ... DO UPDATE` 兼容性风险），mongo 侧以复合键拼接 `_id` 做 `replace_one(upsert=True)`。查询侧规避 A 模式坑：jsonb 路径用 `#>>`、不对 jsonb 文本做 `<> ''` 比较、占位符顺序与文本一致。
- **代价/约束**：需新写一个 repository（PG SQL + mongo motor 双实现）；**不可**改用 `get_db()` 门面，也**不可**与方案 (B) 混用。
  > 注：**主体侧表**（`end_user_org_relations` / `end_user_position_roles` / `org_units`）与**清单来源**（`business_entity_index`）仍是通用壳表，继续走 `get_db()` 门面 —— 只有 `mesc_*` 与 `sys_config` 走原生 SQL。

### 3.9 权限判定键 —— `ontology_id`（`entity_type` 仅作类型标签）

- **决定（2026-10-16）**：权限判定以**本体标识** `ontology_id`（业务系统的本体标识）为准；`entity_type`（customer/order/…）只是**类型标签**，用作前端页面的查询条件，**不参与权限判定**。
- **运行时落点**：`business_semantic_index.semantic_search` 的 `visible_ontology_ids` 过滤按命中的 `ontology_id` 匹配；命中未携带 `ontology_id` 时按**不可见**处理（fail-closed）。
- **数据要求**：业务语义索引写入时须在 metadata 带 `ontology_id`，否则开启 enforcement 后一律不可见。

---

## 4. 现状对照表（关键差异一览）

| 项 | 现有 | 新 DDL | 合并动作 |
|---|---|---|---|
| schema 体系 | `generate_ddl.py` + `schema.sql` | 注释指向 Flyway(Java) | 改落 `deploy/pg/`，加结构化列段 |
| 全局开关 | 无统一表 | 复用 `sys_config`（不存在） | 补 `sys_config` 表 |
| 主体隔离级 | 3 级（无 role） | 4 态（含 role） | role 复用 `position_roles._id` 并参与展开 |
| 权限粒度 | action 码 | ontology / class / column / row | 新层挂数据范围解析 |
| 类↔表 | — | 类是列分组视图，物理表名不入库（`doc_blob['ontology-map']` 解析，`:14-22`） | 保持解耦，`mesc_*` 只存 `class_name` |
| `${user.*}` 主体变量 | — | 语义不成立（端用户 ObjectId ≠ 业务 customer id），已 `enabled=false`（`:201-207`） | 标为能力缺口，需"端用户→业务主体"映射表才能启用 |

---

## 5. 已拍板决策（2026-10-16）

| # | 决策点 | 结论 | 落点 |
|---|---|---|---|
| 1 | `sys_config` 补不补 | **(a) 新建通用配置表** `sys_config(key text primary key, value jsonb)` | §3.2 |
| 2 | 两层关系 / 是否强制 `kg:read` 前置 | **本体层独立可选**，不强制先过 RBAC 功能权限；两层正交、各自可开关 | §3.3 |
| 3 | `defaultMode` 默认 deny/allow | **`enforce=true` 时缺省 deny**（fail-closed） | §3.5 |
| 4 | 后端策略 / 是否走 `pg_compat` 门面 | **(A) 原生 repository**（PG SQL / mongo motor，结构化列，不经门面） | §3.8 |
| 5 | 权限判定键 / `entity_type` 的角色 | **权限以 `ontology_id`（本体标识）为准**；`entity_type` 只是类型标签（前端查询条件），不参与判权 | §3.9 |

> 以上五点已替换原"评审待确认"，文档其余章节已同步。方案 (B)（通用壳 + `COLUMN_MAP` 提升）已否决，不混用。

---

## 6. 开放问题 / 风险

- **`sys_config` 不存在（已决，见 §5）**：已定新建 `sys_config(key text primary key, value jsonb)` 通用配置表，DDL 注释"复用已有"按新表实现。
- **`${user.id}` 语义缺口**：端用户 ObjectId 与业务侧 customer id 不同域，条件恒不成立；启用需先建"端用户→业务主体"属性映射（DDL 注释已标注，当前 `enabled=false`）。
- **组织树来源**：`org_units` 是否承载墨攻组织树未核，影响"含下级"展开。
- **`defaultMode` 与 fail-closed 基调（已决，见 §5）**：已定 `enforce=true` 时缺省 **deny**；`defaultMode` 配置项保留，但开启 enforcement 后未匹配主体按 deny 处理。
- **物理表名不入库**：映射改了规则跟着走、无快照（`:17`），需配套一致性/版本校验，避免映射漂移导致权限误判。
- **本机演示数据单薄**：仅 1 用户/1 组织/1 角色，组织树继承无法演示，需先在墨攻建下级组织与业务角色。
- **PanWeiDB A 模式坑**（落地阶段才处理）：`''`=NULL、`NOT(@>)` 求值错误用 `IS NOT TRUE`、`jsonb` 走 `#>`/`#>>`、占位符顺序——走 `pg_compat` 兼容层时规避。
  > 落地补充（2026-10-16）：本特性**不走** `pg_compat`，坑在 `app/ontology_permission/repository.py` 内自行规避（jsonb 用 `#>>`、空串不比较、占位符顺序与文本一致、upsert 用 UPDATE-then-INSERT）。
- **权限缓存一致性（落地后仍存在）**：chat-api 运行时用**进程内 60s TTL 缓存**，admin-api 的授权变更**无法直接清它**（两服务均未引入 Redis 客户端，无跨进程推送通道）。变更会递增 `sys_config['ontology-permission'].rev` 以保证可观察与可审计，但**生效窗口最长 60s**。若要秒级生效，需引入 Redis pub/sub 或把解析结果做成带 `expires_at` 的共享表。
- **类明细尚未接进生效点**：`mesc_ontology_class_detail` 已建表并提供仓储，但**列投影 / 行条件叠加**还没接进 `semantic_search`（当前只做本体级过滤）。列/行粒度生效前，不要对外宣称"列级/行级权限已生效"。
- **`/internal/*` 网关未放行**：`/admin-api/api/internal/ontology-permissions` 默认不在网关路由表内，部署时需显式加 `location` 并限制来源网段（§6 约束 6）。

---

## 7. 落地阶段

- 阶段 0：建表段（`mesc_ontology_grant` / `mesc_ontology_class_detail` / `mesc_ontology_perm_audit`）+ 补 `sys_config`；`enforce=false`。✅ **已完成**（PanWeiDB + MongoDB 两侧均已执行）
- 阶段 1：管理端配置界面录入（参考 `docs/ontology-permission-mockup.html`），纯预演。✅ **已完成**（`/ontologies` 清单页 + 用户授权弹窗）
- 阶段 2：单本体/单租户 `enforce=true` 灰度。⏳ 开关与页面已就绪，**待运维按租户开启**
- 阶段 3：全量。⏳ 待阶段 2 观察 `gate_events` 命中后推进
- 阶段 4（原设计 §5.10）：业务系统对接 —— 内部权限接口已就绪（`/internal/ontology-permissions`），**待网关放行 + 业务系统接入**；清单副本同步与真实 `ontology_id` 写入待接入后启用

---

## 8. 附录：关键文件与行号

| 文件 | 行号 | 内容 |
|---|---|---|
| `docs/ontology-permission-ddl.sql` | 4-5 | 注释指向 Flyway(Java)，与现栈不符 |
| 同上 | 14-22 | 类≠表，`doc_blob['ontology-map']` 读取时解析 |
| 同上 | 23 | `subject_type='tenant'` 兜底行约定 |
| 同上 | 83-87 | 复用 `sys_config` 全局开关（表不存在） |
| 同上 | 201-207 | `${user.id}` 语义缺口，`enabled=false` |
| `deploy/pg/schema.sql` | 1-2 | 由 `generate_ddl.py` 生成，通用 JSONB 壳 |
| 同上 | 258 / 528 / 645 | `enterprise_session_approval_grants` / `permission_grants` / `resource_grants`（均通用壳） |
| `services/admin-api/app/governance/permission_grants.py` | 32, 34 | `permission_grants` 集合、3 级隔离 |
| `services/admin-api/app/governance/layers/rbac.py` | 17 | `position_roles` 角色集合 |
| `deliverables/gstack/permission-control-data-scope-2026-10-08.md` | 2 章 | 既有五阶段/六层权限模型 |

### 8.1 本特性落地产物（2026-10-16）

| 文件 | 内容 |
|---|---|
| `deploy/pg/ontology_permission.sql` | PanWeiDB 建表段（`sys_config` + 3 张 `mesc_*`，结构化列/复合主键/CHECK/jsonb） |
| `deploy/mongo/ontology_permission.js` | MongoDB 同构集合 + `$jsonSchema` 校验器 + 索引 + 种子 |
| `services/chat-api/app/services/ontology_permission.py` | 运行时解析（fail-closed + 60s 缓存 + `gate_events` 审计） |
| `services/chat-api/app/services/business_semantic_index.py` | 生效点：`SemanticHit.ontology_id` / `EntityRecord.ontology_id` / `semantic_search(visible_ontology_ids=...)` |
| `services/admin-api/app/ontology_permission/{constants,repository,service,subjects}.py` | 常量 / 原生双后端 repository / 服务层 / 四态主体展开 |
| `services/admin-api/app/api/routes/ontologies.py` | 13 条管理端路由（清单 / 配置 / 用户级与四态通用授权 / 审计 / 同步） |
| `services/admin-api/app/api/routes/ontology_permission_internal.py` | §5.8 内部接口（服务凭证鉴权） |
| `apps/admin-web/src/api/ontologies.ts` | 前端 API 层 |
| `apps/admin-web/src/views/ontologies/OntologyCatalogPage.vue` | 清单页（只读 + 开关 + 同步） |
| `apps/admin-web/src/views/ontologies/UserOntologyPermissionDialog.vue` | 用户级授权弹窗 |
| `specs/030-ontology-data-permission/{spec,plan,tasks}.md` | SDD 规约（回溯补规格） |
