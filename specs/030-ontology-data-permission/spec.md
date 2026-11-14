# Feature Specification: 本体数据权限（ontology data-scope permission）

**Feature Branch**: `030-ontology-data-permission`

**Created**: 2026-10-16

**Status**: Draft（已落地部分代码，见 §「实现状态」）

**Input**: User description: "落地本体权限这部分内容"（范围：后端 API、前端页面、建表入库、权限管理写入侧）

> **设计来源**：本规约把三份既有材料固化为 spec/plan/tasks ——
> ① `docs/ontology-permission-ddl.sql`（原始 `mesc_*` 三表设计稿）；
> ② `docs/ontology-permission-merge-plan.md`（合并方案，5 项决策已拍板）；
> ③ `docs/MOGO-Web应用集成方案.md` §5.4–§5.9（清单 / 接口 / 内部对接 / 前端设计）。
>
> **性质说明**：与 027（数据后端迁移）同类的**回溯补规格** —— 代码先于 spec 落地，
> 本文件把已实现的实现口径与剩余任务一并固化，后续按 tasks.md 收敛。
> 冲突时以代码 + 本 spec 的 FR 为准。

## 定位（一句话）

`mesc_*` 三表**不是替换现有 RBAC**，而是给本体（ontology）域新增一层**数据范围（data scope）**权限：
现有体系管"能不能做这个动作"（功能权限 `resource:action[:target]`），本体层管"看到哪些本体 / 类 / 列 / 行"。
两层**正交、各自可独立开关**，不强制 `kg:read` 前置。

## 已定决策（2026-10-16，merge-plan §5 拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | `sys_config` 补不补 | **新建通用配置表** `sys_config(key text primary key, value jsonb)`（非复用） | `deploy/pg/ontology_permission.sql` |
| 2 | 两层关系 / 是否强制 `kg:read` 前置 | **本体层独立可选**，不强制先过 RBAC 功能权限；两层正交、各自可开关 | FR-004 |
| 3 | `defaultMode` 默认 deny/allow | **`enforce=true` 时缺省固定 deny**（fail-closed）；`defaultMode` 仅用于 `enforce=false` 的展示/预演口径 | FR-012 |
| 4 | 后端策略 / 是否走 `pg_compat` 门面 | **(A) 原生 repository**（PG SQL / mongo motor，结构化列，**不经**门面） | FR-002 |
| 5 | 权限判定键 / `entity_type` 的角色 | **权限以 `ontology_id`（本体标识）为准**；`entity_type` 只是类型标签（前端查询条件），不参与判权 | FR-014 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 管理端配置本体数据权限（清单 + 用户级授权 + 撤销）(Priority: P1)

租户管理员在 admin-web 打开「本体清单」页：看到 MOGO 侧的本体清单（只读，来源为业务实体索引聚合出的 `ontology_id`），
在「用户管理」里对某个员工点「本体数据权限」，批量勾选要授予的本体、选择访问模式（read/write/none）与优先级、填备注，
保存后立即生效；已授予的授权可在同一弹窗里逐条撤销。授权变更**可审计**（谁、何时、改了哪个主体/本体）。

**Why this priority**: 这是整个特性的**唯一写入口**。没有授权录入，运行时判定无从谈起；清单 + 授权闭环本身就构成可交付的 MVP（`enforce=false` 下纯配置与预演）。

**Independent Test**: 用一个租户域管理员令牌：`GET /api/ontologies` 拿到清单 → `POST /api/ontologies/users/{uid}/permissions` 批量授予 2 个本体 → `GET /api/ontologies/users/{uid}/permissions` 断言返回 2 条 grant → `DELETE` 撤销 1 个 → 断言只剩 1 条，且 `GET /api/ontologies/audit` 出现 `grant_save` / `grant_delete` 两条记录。全程不依赖运行时解析。

**Acceptance Scenarios**:

1. **Given** 管理员已登录且属于某业务租户，**When** 打开「本体清单」，**Then** 看到「我的可见本体」与「全量清单」两个视图，且顶部提示当前是否处于拦截模式（`enforce`）。
2. **Given** 全量清单非空，**When** 在用户授权弹窗中批量勾选 2 个本体并保存，**Then** 两个本体写入 `mesc_ontology_grant`（`subject_type='user'`），弹窗列表立即出现这两条，`mesc_ontology_perm_audit` 落一条 `grant_save`。
3. **Given** 用户已有 2 条授权，**When** 撤销其中 1 条，**Then** 该本体授权与它的**类明细**一并删除（不留孤儿明细），落一条 `grant_delete`。
4. **Given** 批量授予时勾选了重复项或空串，**When** 保存，**Then** 去重后只写有效项；全部为空则返回 422，不落任何库。

---

### User Story 2 - 运行时按用户解析可见本体，检索按本体过滤（fail-closed）(Priority: P2)

Agent 在 chat-api 侧执行业务语义检索时，按 `(tenant_id, user_id)` 解析该用户**可见的本体清单**，命中里 `ontology_id` 不在可见集的一律隐藏；
解析过程任何异常（DB 不可达、表不存在、超时）都退化为**空集**（不可见），绝不"超时即放行"。

**Why this priority**: 这是权限真正生效的地方，但它是**只读**路径，可独立于管理端配置先行验证（先用脚本灌授权行）。它决定了 `enforce=true` 后系统是否可信。

**Independent Test**: 直接调用 `visible_ontology_ids(tenant_id, user_id)`：给定一组 `mesc_ontology_grant` 行（tenant 兜底 / org / role / user 四态），断言返回集合符合 priority 合并规则；再让数据访问层抛异常，断言返回 `frozenset()` 而非抛错或返回全集。检索侧：给 `semantic_search(..., visible_ontology_ids=frozenset())` 断言返回 `[]`。

**Acceptance Scenarios**:

1. **Given** 同一 `ontology_uri` 上有 `priority=50` 的 `none` 与 `priority=10` 的 `read`，**When** 解析，**Then** 该本体不可见（**priority 大者胜**）。
2. **Given** 同一 `ontology_uri`、同一 `priority` 上有 `write` 与 `none`，**When** 解析，**Then** 该本体不可见（**同优先级取更严格**，fail-closed 偏置）。
3. **Given** 授权行的 `subject_id` 不在该用户展开出的主体集合里，**When** 解析，**Then** 该行被忽略（主体四态过滤）。
4. **Given** 解析过程抛异常，**When** 调用 `visible_ontology_ids`，**Then** 返回空集且**不写缓存**（避免把瞬时故障锁定整个 TTL），同时落一条 `deny` 审计。
5. **Given** 检索命中里某条没有 `ontology_id`，**When** 传入了 `visible_ontology_ids`，**Then** 该命中被隐藏（缺键 = 不可见）。
6. **Given** 调用方未传 `visible_ontology_ids`（`None`），**When** 检索，**Then** 不做过滤（保持既有行为，开关由调用方按 `enforce` 决定）。

---

### User Story 3 - 灰度开关与业务系统侧过滤对接（内部接口）(Priority: P3)

`sys_config['ontology-permission'].enforce` 控制是否真正拦截：`false` 时只配置与预演，页面黄条提示；`true` 时按 fail-closed 缺省 deny。
业务系统通过**服务凭证**鉴权的内部接口按 `(tenantId, userId)` 拉取可见本体，在**业务系统侧**做数据过滤，形成「MOGO 侧授权 → 业务系统侧过滤」闭环。

**Why this priority**: 它决定特性能否安全上线与对外集成。横切 US1/US2，但可独立用单测穷尽验证。

**Independent Test**: 用错误/缺失的 `X-MOVO-Service-Token` 调 `GET /api/internal/ontology-permissions?tenantId=&userId=` 断言 401；用正确令牌断言返回 `{tenantId, userId, count, ontologies[]}`，且 `ontologies[].ontologyId` 与解析结果一致。开关侧：`PUT /api/ontologies/config {enforce:true}` 后断言 `effectiveDefault == "deny"`。

**Acceptance Scenarios**:

1. **Given** 请求头缺少或不匹配服务令牌，**When** 调内部接口，**Then** 返回 401（`hmac.compare_digest` 常量时间比较，fail-closed）。
2. **Given** 有效服务令牌与一个存在授权的用户，**When** 调内部接口，**Then** 返回该用户可见的 `ontologyId` 列表（含 `sourceEntity`/`keyField` 占位字段，业务系统接入后填充）。
3. **Given** `enforce=false`，**When** 查看配置，**Then** `effectiveDefault == "allow"` 且页面提示"预演模式"；**Given** `enforce=true`，**Then** `effectiveDefault == "deny"`。
4. **Given** 授权发生变更，**When** 变更提交，**Then** `sys_config.rev` 递增（变更可被其他进程观察与审计）。

---

### User Story 4 - 双后端行为一致（MongoDB / PanWeiDB）(Priority: P3)

`MOGO_DATA_BACKEND` 在 `mongo` / `PanWeiDB` 之间切换时，`mesc_*` 与 `sys_config` 的**读写行为、字段形状、约束语义一致**，无需改动调用方。

**Why this priority**: mogo 正处于 MongoDB → PanWeiDB 迁移期（027），任何新表都必须双后端可用，否则会变成迁移阻塞项。

**Independent Test**: 同一组操作（upsert grant → 读回 → 删除）在两种后端各跑一遍，断言返回的字典形状一致（`column_list` 都是数组、时间戳都可序列化、`enabled` 都是 bool）。DDL/JS 两份文件字段一一对应。

**Acceptance Scenarios**:

1. **Given** PanWeiDB 后端，**When** upsert 一条已存在的 grant，**Then** 更新而非报唯一键冲突（先 UPDATE、`rowcount=0` 再 INSERT）。
2. **Given** MongoDB 后端，**When** upsert 同一条 grant，**Then** `_id` 由复合键确定性拼接，行为等价于 PG 复合主键。
3. **Given** PanWeiDB（`sql_compatibility=A`），**When** 按 `ontology_id` 聚合清单，**Then** 使用 `doc #>> '{ontology_id}'` 而非 `->>`，且不对 jsonb 文本做 `<> ''` 比较（A 模式下 `''` 等价 NULL）。

---

### Edge Cases

- 空 `tenant_id` 或空 `user_id` → 解析直接返回**空集**，**不查库**（fail-closed 且省一次往返）。
- 授权行 `enabled=false` → 视为不存在（不参与合并），但行保留可审计。
- 授权行缺 `ontology_uri` → 跳过（不允许"空本体"授权）。
- `access_mode` 不在 `{none,read,write}` → 写入口返回 422；读入口对未知值按 `none`（rank 0）参与"取更严格"。
- `priority` 非数字 → 按默认 100 处理，不抛错（避免脏数据打挂判权热路径）。
- 撤销用户授权时存在**类明细** → 明细随授权一并删除（避免孤儿明细压过已删授权）。
- 已授权但索引中尚未出现的本体 → 清单里仍要展示（否则授权页看不到目标），`entityCount=0`。
- 跨租户：`mesc_*` 全部按 `tenant_id` 隔离，A 租户的 tenant 兜底行不得影响 B 租户。
- `/internal/*` 默认**不在网关路由表内** → 部署时需显式加 `location` 并限制来源网段（设计 §6 约束 6）。
- 授权变更后的**跨进程传播窗口**：chat-api 运行时用进程内 60s TTL 缓存，admin-api 不直接清它 → 最长 60s 后才生效（见 FR-016）。

## Requirements *(mandatory)*

### Functional Requirements

**数据结构与后端**

- **FR-001**: 系统 MUST 提供三张结构化表 `mesc_ontology_grant` / `mesc_ontology_class_detail` / `mesc_ontology_perm_audit`，以及通用配置表 `sys_config`；PanWeiDB 侧见 `deploy/pg/ontology_permission.sql`，MongoDB 侧见 `deploy/mongo/ontology_permission.js`，两处字段**一一对应**。
- **FR-002**: 上述表/集合 MUST **不走** `pg_compat` 通用壳门面（其假定 `(id, tenant_id, doc JSONB, created_at, updated_at)`），改用**原生 repository**：PG 走原生 SQL、mongo 走 motor。
- **FR-003**: 系统 MUST 支持四态主体 `subject_type ∈ {tenant, org, role, user}`，并在判权时把用户展开为 `tenant 兜底 + org(含下级) + role* + user 自身` 的主体集合。
- **FR-004**: 本体数据权限层 MUST 为**独立可选**执行层，**不强制**先通过 `kg:read` 等 RBAC 功能权限；是否拦截由 `sys_config['ontology-permission'].enforce` 决定。
- **FR-005**: `mesc_ontology_grant` MUST 以 `(tenant_id, subject_type, subject_id, ontology_uri)` 为唯一键；`access_mode ∈ {none, read, write}`，`priority` 默认 100，`enabled` 默认 true。
- **FR-006**: `mesc_ontology_class_detail` MUST 以 `(tenant_id, subject_type, subject_id, ontology_uri, class_name)` 为唯一键；`access_mode ∈ {inherit, none, read, write}`（`inherit` = 跟随本体），`column_mode ∈ {all, selected}`，`column_list` 为 JSONB 数组，`row_condition` 为可空 JSONB。
- **FR-007**: `mesc_ontology_perm_audit` MUST 记录配置变更（`action ∈ {grant_save, grant_delete, detail_save, detail_delete, enforce_toggle}`，`target_kind ∈ {grant, detail, config}`，含 `target_key` 便于按对象翻历史）。
- **FR-008**: 审计 MUST **不双写**：配置变更落 `mesc_ontology_perm_audit`；运行时判定落既有 `gate_events`。

**判权算法**

- **FR-009**: 判权 MUST 按 `priority` 合并：同一 `ontology_uri` 取 `priority` **最大**者的 `access_mode`。
- **FR-010**: `priority` 相同时 MUST 取**更严格**的 `access_mode`（rank `none < read < write`，取 rank 小者），保证冲突时 fail-closed。
- **FR-011**: 可见判定 MUST 仅认 `access_mode ∈ {read, write}`；`none` 与未知值一律不可见。
- **FR-012**: `enforce=true` 时**未匹配到任何授权行**的主体 MUST 判定为 **deny**（白名单语义）；`defaultMode` 配置项保留，但仅用于 `enforce=false` 的展示/预演口径。
- **FR-013**: 主体侧展开 MUST 支持组织**含下级**（按 `org_units.path_ids` 祖先链展开）与岗位角色（`end_user_position_roles`）。
- **FR-014**: 权限判定键 MUST 为 `ontology_id`（本体标识）；`entity_type` 仅作类型标签（前端查询条件），**不参与判权**。
- **FR-015**: 检索生效点 MUST 在命中**未携带** `ontology_id` 时按**不可见**处理（fail-closed）；调用方传 `visible_ontology_ids=None` 时不做过滤。

**运行时与缓存**

- **FR-016**: 运行时解析 MUST 使用进程内短 TTL 缓存（默认 60s），授权变更后可按 `(tenant_id, user_id)` 或按租户失效；跨进程传播窗口 MUST 在文档中显式声明（当前为 TTL 上限）。
- **FR-017**: 解析过程任何异常 MUST 返回**空集**且**不写缓存**，并落一条 `deny` 审计事件；空 `tenant_id`/`user_id` 直接返回空集且不查库。
- **FR-018**: 授权变更（批量授予 / 撤销 / 开关切换）后 MUST 递增 `sys_config['ontology-permission'].rev`，使变更可被其他组件观察与审计。

**接口**

- **FR-019**: admin-api MUST 提供 `GET /api/ontologies/mine`（当前账号可见本体，登录即可）与 `GET /api/ontologies`（全量清单）。
- **FR-020**: admin-api MUST 提供 `POST /api/ontologies/sync` 同步只读副本；业务系统未接入时 MUST 退化为"按 MOGO 侧业务实体索引聚合"并在响应中**明确标注**（不伪造来源）。
- **FR-021**: admin-api MUST 提供用户级授权接口 `GET|POST /api/ontologies/users/{user_id}/permissions` 与 `DELETE /api/ontologies/users/{user_id}/permissions/{ontology_id}`（批量授予）；并 MUST 提供等价的四态通用形态 `/api/ontologies/subjects/{subject_type}/{subject_id}/permissions`。
- **FR-022**: admin-api MUST 提供 `GET|PUT /api/ontologies/config` 读写 `enforce` 开关，以及 `GET /api/ontologies/audit` 查询变更审计。
- **FR-023**: admin-api MUST 提供内部接口 `GET /api/internal/ontology-permissions?tenantId=&userId=`，以**服务凭证**（`X-MOVO-Service-Token`，`hmac.compare_digest` 常量时间比较）鉴权，返回该用户可见本体。
- **FR-024**: 「本体清单」MUST **只做展示**，**不提供**本体 CRUD（本体定义与数据都在业务系统）。

**前端**

- **FR-025**: admin-web MUST 提供 `/ontologies` 页面（只读展示清单 + 开关状态 + 同步入口）与用户级授权弹窗；用户管理页用户行 MUST 提供「本体数据权限」入口。

**双后端一致性**

- **FR-026**: upsert MUST 在 PanWeiDB 上规避 `ON CONFLICT ... DO UPDATE` 兼容性风险（先 UPDATE、`rowcount=0` 再 INSERT），在 mongo 上以复合键拼接的 `_id` 做 `replace_one(upsert=True)`。
- **FR-027**: PanWeiDB（`sql_compatibility=A`）查询 MUST 规避已知坑：jsonb 路径用 `#>`/`#>>`、不对 jsonb 文本做 `<> ''` 比较、占位符参数顺序与 SQL 文本出现顺序一致。

### Key Entities

- **本体授权（mesc_ontology_grant）**：某主体在某个本体上的访问模式。主体四态 + 本体标识 + `access_mode` + `priority` + `enabled` + 备注。
- **类明细（mesc_ontology_class_detail）**：本体授权之下的细化 —— 类级访问模式（`inherit` 跟随本体）、列子集、行过滤条件。类本质是"某张表的列分组视图"，物理表名**不入库**，由 `doc_blob['ontology-map']` 读取时解析。
- **变更审计（mesc_ontology_perm_audit）**：配置变更流水，按 `target_key` 可翻某个对象的历史。
- **全局开关（sys_config）**：`key='ontology-permission'`，值含 `enforce` / `defaultMode` / `rev`。
- **本体清单（只读视图）**：聚合自业务实体索引的 `ontology_id`，附类型标签与已配置授权数；**不落新表**。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 管理员从打开用户授权弹窗到完成 5 个本体的批量授予，操作 ≤ 3 步（勾选 → 保存 → 列表刷新可见），且全程无需刷新页面。
- **SC-002**: 判权解析在 60s 缓存命中时为**零 DB 往返**；缓存未命中时对 `mesc_ontology_grant` 的查询为**单次**批量查询（不做 N+1）。
- **SC-003**: `enforce=true` 下，未授权用户的检索结果条数为 **0**（fail-closed 可验证），且不出现"部分可见"的中间态。
- **SC-004**: 同一组 CRUD 操作在 MongoDB 与 PanWeiDB 两种后端下返回**同形**结果（字段名与类型一致），差异为零。
- **SC-005**: 所有配置变更 100% 落审计（`grant_save` / `grant_delete` / `enforce_toggle` 各至少一条可查）。

## Assumptions

- 本体定义与本体数据都由**业务系统**提供，MOGO 侧只保存只读副本/聚合视图；本阶段不接业务系统，`sourceEntity`/`keyField` 返回空串并在接口文档标注。
- 端用户 ObjectId 与业务侧主体 id **不同域**，`${user.*}` 主体变量语义暂不成立 —— 需先建"端用户 → 业务主体"映射表才能启用（原 DDL 已把该示例行标 `enabled=false`）。
- `org_units` 承载的组织树用于"含下级"展开；组织树来源与业务系统的一致性校验不在本特性范围。
- 物理表名不入库（类 ↔ 表由 `doc_blob['ontology-map']` 运行时解析），因此**映射漂移**需要配套一致性校验，本特性先按"改了规则跟着走、无快照"实现。
- admin-api 目前**没有**按路由校验权限码的机制，故本特性沿用 `get_current_admin_user` 的租户域校验，不引入孤立的 `ontology:list/grant/sync` 权限码。
- 业务系统接入（真实 `ontology_id` 写入索引、清单副本同步）属后续阶段；本阶段索引写入方**不**填 `ontology_id`（用户明确要求业务系统集成后再接）。

## 跨特性关系（被依赖方视角）

| 相关特性 | 关系 |
| --- | --- |
| 001 gatekeeper-governance | 本体层是**数据范围**层，与 gatekeeper 的 **action 判定**解耦；运行时判定审计复用 `gate_events`，不新增第六层之后的第七层 |
| 006 position-rbac-admin | `role` 主体复用 `position_roles._id`；角色展开与 `rbac.py::expand_role_to_codes` 同源 |
| 014 business-semantic-index | 检索生效点落在 `business_semantic_index.semantic_search`；索引写入方需带 `ontology_id`（业务系统集成后接入） |
| 015 knowledge-graph-layer | 同为"本体/图谱"域，但 015 管图谱构建与融合，本特性只管**可见性**，不重叠 |
| 027 mongo-to-panweidb-migration | 本特性所有新表**双后端可用**；原生 repository 是 027 决策 A 在结构化表上的首个落地样板 |
| 022 security-hardening | 内部接口走服务凭证（022 T019/T020/T028 机制）；`/internal/*` 需显式放行 + 来源限制（022 §6 约束 6） |
