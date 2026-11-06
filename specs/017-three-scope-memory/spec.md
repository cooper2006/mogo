# Feature Specification: Three-Scope Memory (personal / project / department)

**Feature Branch**: `017-three-scope-memory`

**Created**: 2026-07-08

**Status**: **Design Baseline — 决策已闭环**（v3 修订稿，2026-11-06）

**B1 落地状态**: ✅ 已完成并通过回归（见 §9）。本轮同时落地了 P0 身份解析修复；范围改名（D4）尚未执行，仍在维护窗口内一次性切换。

**权威设计来源**: [`design-2026-11-05-project-department-scopes.md`](./design-2026-11-05-project-department-scopes.md)（v3，含数据流 §5、业务流 §6、双端功能 §7、可见性算法 §4、迁移 §10、验收 §11）。本文件是**规格与验收口径**；详细算法、字段、接口载荷以设计文档为准，冲突时以设计文档 v3 为准。

**Input（用户口径，累计）**:
1. `workspace` 范围等同于**项目**（`projects` 表）；`org` 范围使用**部门**（`org_units` 表）概念。
2. 项目可扩展成员 → 项目范围是多成员共享语义（由 `specs/049-project-members` 落地）。
3. 功能层面参考**插件管理 / Skill 管理，从 admin / user 两端规划**。
4. 成员入口落在 user-web 项目右侧扩展菜单；管理端「项目管理」页数据流由 049 修复。
5. **（v3 裁决）** D3 部门可见性含后代；D4 `workspace/org → project/department` **直接改名、不设兼容过渡**；D7/D8 安全必项按设计执行；C-7 成员变更审计补上。

---

## 修订说明（v3 相对 2026-07-08 原稿）

| 项 | 原稿 | v3 |
|---|---|---|
| 状态 | `Draft` | Design Baseline，全部决策闭环 |
| 范围 | 个人 / Workspace / 组织 | 个人 / **项目**(`projects._id`) / **部门**(`org_units._id`) |
| 成员来源 | 未定义的「工作区成员」 | 049 `projects.member_user_ids` ∪ `projects.user_id` |
| 身份 | 调用方传 `viewer_id/role/is_workspace_member` | 服务端唯一 `MemoryViewerContext`（修 P0） |
| 角色 | 隐含「全能力管理员」 | 006 `end_user_position_roles` → `position_roles.system_key` |
| 部门可见性 | 「全组织」 | 所在部门 + **全部后代**，不含祖先（D3） |
| 改名 | 无 | **一次性全量替换 + 离线幂等迁移 + 原子切换**（D4），无别名 / 双写 / 回退 |
| 双端界面 | 无 | admin `/memories` + user「我的记忆」+ `/audit` 记忆 module |
| FR 编号 | FR-1 ~ FR-20 | **A–J 分组**（§7），标注与原 FR 的关系 |
| 验收 | 6 条定性描述 | SC-1 ~ SC-15 可测口径（§8） |

> 原稿中的 FR-6「复用 005 个人知识底层存储」、FR-19「会话参与者集合」等假设经 2026-10-03 落地审计与 2026-11-05 代码复核后不成立或需改写，已在 v3 重新表述，不再沿用。

---

## 1. 术语与主数据映射

| 本文术语 | 机器标识 / 集合 | 归属判定 | 说明 |
|---|---|---|---|
| 个人 | `personal` / `memories.owner_id` | `owner_id == viewer.user_id` | 仅本人 |
| 项目 | `project` / `projects._id` | `(project_id, project_owner_id) ∈ visible_project_keys` | 049 已落地的多成员共享项目 |
| 部门 | `department` / `org_units._id` | `department_id ∈ visible_department_ids` | 含后代（D3） |
| 租户 | `tenant_id` | `add_tenant_scope` | 所有查询必带 |

- **`project_owner_id` 必须冗余在记忆文档里**（N1）：`projects` 唯一索引是 `{tenant_id, user_id, workspace_id}`，`_id` 在租户内不保证唯一；只按 `project_id` 判定会串读他人项目记忆。
- **`"default"` 项目不得承载项目记忆**（N2）：049 为产品兜底让该行对同租户所有用户可见；017 刻意不继承该豁免，否则项目记忆会全租户泄露。
- 与 042 配额的区别：042 的「直接成员」是**计量**口径，017 的部门可见性是**授权**口径，两者不得互相替代。

## 2. 决策台账（全部已裁决，无待拍板项）

| 编号 | 裁决 | 来源 |
|---|---|---|
| D1 | 项目多人共享（`projects.member_user_ids`），修订 ADR-8 D1 | 049 / ADR-9 |
| D2 | 会话默认：单人（有有效项目）→ `project`，否则 `personal`；多人 → `project` | 回归 017 原口径 |
| **D3** | **部门可见性 = 所在部门 + 全部后代、不含祖先、跨租户 fail-closed** | 用户 2026-11-06 裁决 |
| **D4** | **直接全量改名，不设兼容过渡**（偏离 v2 推荐）；存量由离线迁移一次性转换 | 用户 2026-11-06 裁决 |
| D5 | 成员模型 = 内嵌 `member_user_ids`（非独立集合） | 049 已落地 |
| D6 | admin 项目管理页同库直读 `projects` | 049 已落地 |
| **D7** | `default` 隔离按 N2 **强制执行** | 用户确认 |
| **D8** | `project_owner_id` 消歧按 N1 **强制执行** | 用户确认 |
| **C-7** | 成员变更审计 `project.member.*` **纳入首期必做** | 用户 2026-11-06 裁决 |

> 后续若要恢复兼容层或改为「精确同部门」，必须另起决策记录并重新评估 §10 迁移与 SC-15。

## 3. User Scenarios

### US1 (P1) — 三范围隔离与共享
记忆按 `personal / project / department` 隔离，项目记忆对项目创建者与被邀请成员共享，部门记忆对所在部门及后代可见。

**Acceptance**: 写入各范围 → 仅授权者可见；跨租户 / 非成员 / 非本部门 / 空身份 / 未知 scope / 已归档 → 一律不可见（统一 404）；同名 `project_id` 不同创建者互相不可见；`default` 项目写入被拒。

### US2 (P1) — 范围指定与默认策略
写入可显式指定范围；未指定按会话类型与项目上下文解析；`project_owner_id` 与 `department_id` 一律服务端解析，客户端传值忽略。

**Acceptance**: 显式写 `project` 且目标不在 `visible_project_keys` → 403；`project_id="default"` → 400；沉淀遇 default 回落 `personal` 并回显 `resolved_from="default_fallback"`；范围提升到 `department` 需 `full_access_admin` + 审计。

### US3 (P1) — 会话沉淀与渐进检索
002 `SessionEnd`（经 009 hook）沉淀为分层记忆；RAG 检索按可见性过滤，默认只注入 L0+L1，产出可回看的 `retrieval_trace`。

**Acceptance**: 沉淀产 L0/L1/L2 + `source_session_id`/`source_type`；`ended_at` 幂等，`end → delete` 不重复；`skipped` 非空且原因可归类；按 `trace_id` 可回看；提升后分层字段 / provenance / `archived` / `project_owner_id` 全保持。

### US4 (P1) — 双端治理与使用
admin 侧治理全租户记忆，user 侧管理自己的记忆；两端共用同一 `visible_to` 判据。

**Acceptance**: admin `/memories` 指标卡 / 跨范围列表 / 详情抽屉 / 提升审批 / 策略配额；user「我的记忆」双 Tab（我的 / 共享给我）/ 增删改 / 提升申请；所有治理动作在 `/audit` 可查；不可见即 404；记忆不挂 `/assets`（045 排除项）。

## 4. 数据流（目标态，详见设计文档 §5）

| # | 流 | 关键约束 |
|---|---|---|
| DF-1 | 身份解析 | `resolve_session_user` → `MemoryViewerContext`（角色 / 部门集合 / 项目集合全部服务端解析）→ 所有入口共用 |
| DF-2 | 创建 / 更新 | 入口校验 scope → 反查 `projects.user_id` 固化 `project_owner_id` → `await store.save()`；更新走增量 `$set`（D-6） |
| DF-3 | 会话沉淀 | 002 `SessionEnd` → 009 dispatcher → `sediment.py` 读 `session_doc.project_id`（046 三级回退）→ 分层写入 |
| DF-4 | RAG 检索 | `MemoryStore.list_for_viewer(viewer)` → `scope_filter` → `progressive_memory_retrieval` → L0/L1 候选 + trace → 注入上下文 |
| DF-5 | 021 地址解析 | `mogo://memory/<scope>/<owner>/<id>/[tier]` → 只委托 017 `visible_to`，地址层不重写鉴权 |
| DF-6 | 提升 / 治理 | `full_access_admin` → `promote` → 001 审计；普通用户走审批状态机 |
| DF-7 | 生命周期 / 组织变更 | 衰减循环 + `touch` 重置；离职 / 调岗 / 049 成员移除后动态重算，不固化名单 |

> **D4 切换流**：M1 代码全量替换（不发布）→ M2 冻结写入 + 幂等迁移 S1–S7 → M3 原子切换 + 解冻 → M4 对账清理。无别名兜底，**回滚必须「代码回退 + `--reverse`」成对执行**。

## 5. 业务流（目标态，详见设计文档 §6）

B1 身份解析 → B2 范围判定 → B3 写入校验 → B4 沉淀 → B5 检索 → B6 地址解析 → B7 提升审批 → B8 治理动作 → B9 生命周期 → B10 离职/调岗 → B11 成员变更（049 + C-7 审计）→ B12 双端管理 → B13 迁移切换。

关键不变量：**成员变更不改记忆**（动态解析，P2）；**一次会话至多沉淀一次**；**不可见即不泄露**（批量解析逐项 `visibility_denied`，不返回内容字段）；**范围轴与密度轴正交**（scope 管谁能看，tier 管喂多少）。

## 6. 功能点清单前的优先级约定

P0 = 前置 / 不修不可用；P1 = 目标态核心；P2 = 治理增强。标【049】者为复用既有能力，017 不新建、不修改其业务语义。

---

## 7. Functional Requirements（A–J 重编号）

### A. 身份与上下文（P0）

| FR | 要求 |
|---|---|
| A-1 | 唯一 `MemoryViewerContext`（不可变），字段：`tenant_id` / `user_id` / `role_keys` / `is_full_access_admin` / `primary_department_id` / `visible_department_ids` / `visible_project_keys` / `active_project_id` / `session_participants` |
| A-2 | 所有入口（HTTP、RAG 适配器、021 地址解析、会话沉淀、双端管理）只接受服务端构造的上下文；**禁止**从 auth 字典取 `user_id` / `role` / `is_workspace_member`，禁止客户端自报身份 |
| A-3 | `role_keys` 从 006 `end_user_position_roles` → `position_roles.system_key` 解析（兼容 `role_id` 形式）；`is_full_access_admin` 由 `role_keys` 推导 |
| A-4 | 部门集合：`end_user_org_relations`（**不带** `status` 过滤，N3）∪ `end_users.primary_org_id` → `org_units.path_ids` 展开后代（D3）；跨租户 fail-closed |
| A-5 | 项目集合：按 049 契约构造 `visible_project_keys = {(project_id, project_owner_id)}`，显式排除 `"default"` 与 `status=archived` |
| A-6 | 空 / 不完整上下文、任一解析失败 → **fail-closed**（401 或空集合），绝不回落宽松默认值 |

### B. 范围模型与可见性（P0/P1）

| FR | 要求 |
|---|---|
| B-1 | 范围轴封闭为 `personal / project / department`，`Memory.__post_init__` 拒绝其它值 |
| B-2 | `project` 绑定 `projects._id`；可见性 = 创建者 ∪ `member_user_ids` 成员【049】 |
| B-3 | `department` 绑定 `org_units._id`；可见性 = 所在部门 + 全部后代、不含祖先（**D3 裁决**） |
| B-4 | `visible_to` 是唯一可见性判据，021 只委托不重写，判定基于存储记录而非请求参数 |
| B-5 | 范围与上下文标签分离（tag 不参与鉴权） |
| B-6 | **（D4）** 写入 / 列表筛选 / 地址解析三处对旧值 `workspace` / `org` / `workspace_id` / `org_id` 一律拒绝（`400 scope_invalid` / 404）；**不设别名、`normalize_scope`、双写、三级回退** |
| B-7 | 跨租户 / 空归属 id / 未知 scope / 已归档一律不可见，统一 404 |
| B-8 | **（N1 / D8）** `project` 记忆必带 `project_owner_id`，按 `(tenant_id, project_id, project_owner_id)` 判定；缺字段 fail-closed |
| B-9 | **（N2 / D7）** `"default"` 不得承载 `project` 记忆：显式写 400、沉淀回落 `personal`、历史归档、地址解析 404 |

### C. 对 049 的消费契约（P0/P1）

| FR | 要求 |
|---|---|
| C-1 | 【049】`visible_project_keys` 按 `projects.find({tenant_id, $or:[user_id, member_user_ids], status:active})` 构造，排除 `_id:"default"` |
| C-2 | 【049】成员新增 / 移除 / 项目归档后**立即生效**（动态解析），017 不监听事件、不缓存名单、不写 `projects` |
| C-3 | 【049】成员写权限（仅创建者 403 / default 400）与候选端点部门子树过滤，017 不重复实现、不绕过 |
| C-4 | 【049】user-web「成员」弹窗与 admin 项目列表（成员数 / 额度 / 用量 / 成本 / policy）保持原样，017 仅回归不破坏 |
| C-5 | 【049】admin `memberCount = len(member_user_ids)`（不含创建者），017 展示共享成员数不得改写 |
| C-6 | 017 详情 / 列表按 `project_id + project_owner_id` 消歧回显项目名；查不到显示「已归档/已删除」 |
| **C-7** | **（v3 必做）** 在 049 `PATCH /projects/{id}` 按 diff 落 `project.member.granted` / `project.member.revoked`（`feature="049"` → 001 审计），admin `/audit`「记忆管理」module 可查；**不改 049 业务语义、不新建成员端点**；审计失败只留观测日志、不阻断 PATCH |
| C-8 | 017 **不得**引用 `quota_projects`、假定存在 `project_members` 集合或 `projects.sharing_enabled` 字段（防回归） |

### D. 写入与分层（P1）

| FR | 要求 |
|---|---|
| D-1 | 显式 scope + 服务端校验；`project_owner_id` / `department_id` 一律服务端解析，客户端传值忽略 |
| D-2 | 默认策略：单人会话有有效项目上下文 → `project`，否则 `personal`；多人会话 → `project`（无项目上下文回落 `personal`） |
| D-3 | 同一内容写入多范围各存独立副本，不走跨范围去重，检索时按可见性分别呈现 |
| D-4 | 超长优先分层；仅 `tierable=false` 且 L2 超硬上限时拒绝写入并明确提示 |
| D-5 | 写时摘要 + 读时惰性补全**两条路径都有生产注入点**；缺摘要须告警，不得静默退化为全文 |
| D-6 | 更新走增量 `$set`，保留分层 / provenance / `archived` / `project_owner_id`（修 promote 全量替换清空字段） |
| D-7 | 写入必须 `await` motor（`replace_one` / `update_one`） |

### E. 会话沉淀（P1）

| FR | 要求 |
|---|---|
| E-1 | 002 `SessionEnd` → 009 → 017 链路保持，`ended_at` 幂等为唯一去重判据 |
| E-2 | 项目上下文从 `session_doc.project_id` 取（046 三级回退），同时反查 `projects.user_id` 写 `project_owner_id` |
| E-3 | 沉淀产 L0/L1/L2 + `source_session_id` / `source_type=session` |
| E-4 | 多人会话默认 `project`；`default` 回落 **`personal`**（不回落 department） |
| E-5 | 沉淀失败不阻塞会话结束，但必须落观测日志 |

> E-2 的「三级回退」指**会话取值来源优先级**（046 FR-011），与 D4 删除的「旧字段回退读取」不是同一概念。

### F. 检索与轨迹（P1）

| FR | 要求 |
|---|---|
| F-1 | 记忆进 RAG（005），检索前按 scope 过滤；所有调用点必须传完整 viewer 上下文（含 `viewer_org_id`） |
| F-2 | 默认只注入 L0+L1，L2 仅显式请求；降级命中需标注 |
| F-3 | `retrieval_trace` 含 candidates + **非空 skipped**，原因含 `scope_invisible` / `default_project_excluded` / `missing_project_owner` |
| F-4 | 轨迹落观测通道（非 001），按 `trace_id` 回看；高价值命中抽样进 001 |
| F-5 | **（D4）** 地址往返一致仅在 `personal/project/department` 新值域内成立；旧段地址由迁移脚本改写持久化引用，运行时返回 404 |

### G. 提升与治理（P1）

| FR | 要求 |
|---|---|
| G-1 | 提升到 `department` 需 `full_access_admin` 且目标部门在 `visible_department_ids` 内 |
| G-2 | 提升 / 部门范围写入进 001 审计，失败留痕不阻塞主流程 |
| G-3 | 普通用户提升需审批（与 001 `portal_requests` 状态机联动） |

### H. 生命周期与组织变更（P1/P2）

| FR | 要求 |
|---|---|
| H-1 | 衰减周期可配置（`MEMORY_DECAY_DAYS` 注入，不得硬编码 30 天） |
| H-2 | 读取命中调用 `lifecycle.touch()` 重置计时（生产接线） |
| H-3 | 离职 / 删号：personal 与 project 记忆失效，department 记忆保留且不依赖创建者 |
| H-4 | 部门移动后 `visible_department_ids` 动态重算 |
| H-5 | 049 成员移除后 `visible_project_keys` 动态重算，不固化名单 |
| H-6 | 项目归档保留历史记忆但退出 RAG 默认检索 |

### I. 双端功能（P1/P2）

| FR | 要求 |
|---|---|
| I-1 | admin `/memories`：指标卡 / 跨范围列表 / 筛选 / 详情抽屉 / 治理动作 |
| I-2 | admin 可见范围配置（部门 / 岗位 / 指定员工 + 含下级）、策略配置、配额 |
| I-3 | admin 独立审计视图复用 `/audit`，新增「记忆管理」module（纳入 `memory.*` 与 `project.member.*`） |
| I-4 | user「我的记忆」：双 Tab / 搜索 / 卡片 / 增删改 / 提升申请 / 通知（**不含成员编辑**，归 049） |
| I-5 | 两端共用响应契约、分页、唯一可见性判据、审计桥；不可见一律 404 |
| I-6 | 权限：admin `get_current_admin_user` + 权限码；user `require_end_user_principal` + scope 断言 |

### J. 契约与一次性切换（P1/P2）

| FR | 要求 |
|---|---|
| J-1 | `/api/v1/memories` 路径不变，新增 `project_id` / `project_owner_id`（只读回显）/ `department_id`；响应回显 `actual_scope` 与 `resolved_from`（`explicit / default / default_fallback / sediment`，**无 `legacy_alias`**） |
| J-2 | `memories` schema 按设计文档 §2.2；幂等迁移脚本（dry-run / `--apply` / `--reverse` / 失败清单） |
| J-3 | 不引用 `quota_projects` / `project_members` / `project_memories` / `organizations` 作范围主数据 |
| J-4 | 全部对外文档同步新口径（017 五件套、021、`contracts/memory-context-contract.md`、INDEX、049 spec/tasks） |
| **J-5** | **（D4）全仓一次性替换清单**：`MemoryScope` / `Visibility` / `SCOPE_VISIBILITY` / `Memory` dataclass、`sediment.py`、`retrieval.py`、`store.py`、`address.py`、`endpoints/memory.py`、`adapters.py`、`context_space/`、契约与 017/021 SDD；替换后旧字面量仅允许残留在迁移脚本与历史说明 |
| **J-6** | **（D4）切换顺序约束**：M1 代码替换与 M2 数据迁移在同一维护窗口原子切换，切换前冻结写入；回滚必须走 `--reverse` 连数据一起回退；S4/S7 的 `archived` 标记不自动撤销 |

---

## 8. Success Criteria（SC-1 ~ SC-15）

| # | 可测标准 |
|---|---|
| SC-1 | 用**真实** auth 契约与真实 `projects`（含 `member_user_ids`）/ `org_units` fixture 跑端点测试；跨用户 personal、非成员 project、跨部门 department 三类越权全部失败且返回 404 |
| SC-2 | 049 增加成员后该成员可见该项目记忆；移除后下次读取即失效，无需改 017 数据；创建者始终可见 |
| SC-3 | 017 显式写 `project_id="default"` 返回 400、沉淀回落 `personal`、同租户其他用户不可见 |
| SC-4 | **（D3）** 所在部门及全部后代可见、下级不可读上级；部门移动后集合自动变化；无 `status` 字段的用户仍能解析出非空集合；跨租户 fail-closed |
| SC-5 | 多人会话沉淀落 `project`（含 `project_owner_id`），单人按 D-2；L0/L1 非空，`source_session_id` 可回查 |
| SC-6 | 提升后分层字段 / provenance / `archived` / `project_owner_id` 全保持；审计事件可查 |
| SC-7 | RAG 默认只注入 L0+L1；`skipped` 非空且原因可归类；按 `trace_id` 可回看 |
| SC-8 | 用户停用/删号后 personal/project 不可见，department 仍对部门可见 |
| SC-9 | 049 回归：管理端 `/projects` 有数据、四列有值、join 不丢行、`/projects/{id}/policy` 可用；017 改动后行为不变 |
| SC-10 | **（D4）** 迁移脚本连续两次执行第二次 0 条写入；`--reverse` 能还原 S1/S2/S6 且不撤销 S4/S7 的 `archived`；三类孤儿全部进清单且无猜测性归属 |
| SC-11 | admin `/memories` 与 user「我的记忆」可见性结果一致（同一 `visible_to`）；治理动作在 `/audit` 可查 |
| SC-12 | 017 + 021 相关单测全绿，**无 monkeypatch 出契约外字段的用例**；测试不得假定 `project_members` 集合或 `sharing_enabled` 字段 |
| SC-13 | 同名 `project_id` 不同创建者的项目记忆互相不可见；历史缺 `project_owner_id` 的记忆一律不可见 |
| **SC-14** | **（C-7）** 成员变更事件在 `/audit` 两个 module 可查、payload 含 diff 与 actor；只改 `title`/`status` 或 diff 为空不发；审计桥异常时 PATCH 仍成功且响应码不变；049 既有语义回归全绿 |
| **SC-15** | **（D4）** 全仓旧字面量仅残留在迁移脚本与历史说明；`memories` 中旧 scope / 旧字段 0 条；写入旧 scope、请求旧字段、解析旧地址分别 400 / 400 / 404；M1 与 M2 在同一维护窗口完成，`--reverse` 演练通过 |

## 9. 落地状态（2026-11-06，B1 已完成）

**已落地（本轮）** — 对应 `tasks.md` B1：

- 新增 `app/memory/viewer.py`：`MemoryViewerContext` + `build_viewer_context()` + `resolve_viewer_context()` + `resolve_viewer_from_identity()` + 三个 fail-closed 查询（006 角色 / 049 项目成员 / `end_users.primary_org_id`）。**B1 版本字段**：`tenant_id` / `user_id` / `role_keys` / `viewer_org_id` / `visible_workspace_ids`；A-1 的 `visible_department_ids` / `visible_project_keys` / `active_project_id` / `session_participants` 由 B2 补齐。
- 修复 §7 A-2 / A-3 / A-6 的生产路径：`api/endpoints/memory.py` 四个端点、`api/endpoints/context_space.py` 两个端点全部改走统一上下文；不再读取 auth 字典里不存在的 `user_id` / `role` / `is_workspace_member`。
- 修复 RAG 适配器：`adapters.py` 的 `context.get(...)`（对冻结 pydantic 模型必然抛 `AttributeError`、被 `except` 吞掉导致整条记忆检索路径恒空）改为服务端身份解析，补齐 `viewer_org_id`，并让 `memory_candidates` 真正进入返回载荷。
- `visible_to` 增加空 `viewer_id` / 空 `owner_id` 的 fail-closed 防御。
- 回归测试：`test_memory_endpoints.py` 改为**真实 auth 契约**夹具并新增 7 个越权 / 角色 / 成员用例；新增 `test_memory_viewer.py`（15 例）与 `test_rag_viewer_wiring.py`（2 例）；`test_context_endpoints.py` 同步改契约并新增透传断言。
- 实测：`tests/memory` + `tests/context_space` + 两个 `knowledge_search` 用例文件 **171 passed**；交叉回归 `tests/enterprise_capabilities/runtime` + `test_knowledge_graph.py` + `test_a2a.py` **81 passed**；`compileall` 通过。

**未落地**（B2 起，见 `tasks.md`）：D4 范围改名与迁移（必须与数据迁移在同一维护窗口原子切换）、`visible_project_keys` 二元组与 N1/N2、部门集合展开（D3）、双端页面、C-7 审计钩子、生命周期与离职处置、promote 增量 `$set`、写时摘要注入。

## 10. Non-Goals

- 不实现跨租户/跨组织记忆共享。
- 不改变 005 个人知识库与 049 项目成员的业务契约；017 只消费、不新建成员端点、不写 `projects`。
- 不内置摘要模型 / embedding 训练：L0/L1 由上游 Agent 写入时生成，或检索时惰性补全；017 只负责存储与按需回退。
- 不实现记忆的跨实例同步。
- 不把记忆挂到 045 `/assets` 资产中心。
- **不提供 `workspace` / `org` 的运行时兼容**（别名、双写、三级回退），历史数据只由离线迁移脚本转换（D4）。

## 11. Assumptions & Dependencies

- 前置依赖：002 `SessionEnd`、009 hook dispatcher、021 统一地址空间、030 本体数据权限、046 项目维度、049 项目成员 + 管理端项目管理、001 审计、006 RBAC。
- 049 的「默认项目对同租户可见」是产品兜底，017 明确不继承（N2）；这是**刻意的不一致**，防止后续被「对齐 049」改回去。
- `end_user_org_relations` 三处写入方不写 `status`，030 读取带该过滤；017 跟随 049 `member-candidates` 不带过滤的已验证写法（N3），数据修复为可选项、不作阻塞。
- 042 配额「直接成员」与 017 部门可见性用途不同，文档标注差异，不擅改配额口径。
- 技术实现细节（算法、字段、迁移脚本步骤、接口载荷、双端组件）由设计文档与 `plan.md` 承载；任务拆分与验收勾选见 `tasks.md`。
