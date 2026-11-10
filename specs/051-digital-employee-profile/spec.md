# Feature Specification: 数字员工档案（agent 组装单元 + 门户认领 + 意图路由）

**Feature Branch**: `051-digital-employee-profile`

**Created**: 2026-11-09

**Status**: Draft

**Input**: 整合方案 §4.2：新增"数字员工"实体——面向业务用户的 agent 组装单元：员工 = 岗位档案（能力边界）+ 知识库挂载 + 记忆 scope + 模型配置 + Harness profile + 绑定 SOP/编排 + 定时任务归属。B1 实体与绑定、B2 分发与路由两阶段；门户从"申领应用"升级为"认领员工"。

> **设计来源**：本规约来自 `docs/MOGO-StaffDeck整合方案.md` §4.2（2026-11-09 代码级勘察结论）。StaffDeck 为 AGPL-3.0，**仅借鉴产品设计，不拷贝代码**。
>
> **性质说明**：**B1 已实现（2026-11-09，tasks 19/30）**——员工实体 + 会话绑定注入 + 资产中心类型 + 用户端点 + 成本归因接线落地；前端（admin-web 管理页 / user-web 门户 + 会话选择器）已交付，双端 vue-tsc 0 错误；**B2 大部分落地（2026-11-09，T008/T020/T021/T022/T025/T026/T027/T030 已勾，29/30）**——IM 渠道-员工意图路由（确定性关键词匹配 + 默认兜底，`im_gateway/routing.py` + `binding_store.py` + 审计事件）13 测试全绿 + 员工级 API Key（`app/employees/api_keys.py` 双服务同源 + `api_key_auth.py` X-API-Key 认证 + admin 端点 + chat `/employees/me/by-key`，19 测试全绿）+ 员工模板上架经 053（T022 已接线）+ B2 测试/回归/生产接线（IM+门户+员工 121 项全绿、`check_production_wiring.py` 9 模块通过）+ E2E 行为验证（`_bind_session_employee` 5 项集成测试：档案/知识库/记忆/模型注入 + 404/409/422）；**T028（前端手工验收）待人工执行**。OQ-1~OQ-4 已按 spec 已定默认值消解并回填。
>
> **背景事实（代码级核实，2026-11-09）**：006 岗位角色是**人的 RBAC**——`services/admin-api/app/api/routes/position_roles.py:19-27`（`PositionRolePayload`：capabilities 开关 + toolAccessMode/skillAccessMode 白名单 + 用户绑定），其常量已预留 `AGENT_CAPABILITY_KEYS`（`app/position_roles/constants.py`）；045 资产中心统一坐标 `(asset_type, asset_key)`（`services/admin-api/app/services/capability_assets/registry.py`，现类型不含 employee）；037 统一门户已落地（目录 → 自助认领 → 001 审批 → 即用）；017 三范围记忆（personal/project/department）；019 Harness 弹性 profile；040 模型分级路由；`app/scheduled_tasks/` 已实现（无员工归属维度）；013 ChannelRouter 会话-渠道绑定（`im_gateway/router.py`，无渠道-员工与意图路由）；049 项目成员可见性口径（"我的 ∪ 我参与的"）。

## 定位（一句话）

在 mogo 既有治理与资产体系之上增加"数字员工"这一**面向业务用户的组装单元**：把能力白名单、知识库、记忆 scope、模型配置、Harness profile、SOP 绑定组装成一个有档案、可认领、可路由的员工实体；**不改造 006 岗位角色（人的 RBAC），不新建治理旁路**——员工的一切执行仍过 001 六层门禁。

## 已定决策（2026-11-09，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 员工与岗位角色的关系 | **新建 `employees` 实体，不改造 `position_roles`**：岗位角色继续管"人"的 RBAC；员工的能力边界**沿用白名单范式**（capabilities 开关 + 工具/Skill 显式列表，参照 `PositionRolePayload` 结构与 `AGENT_CAPABILITY_KEYS`），但绑定对象是 agent 会话而非人 | chat-api/admin-api 员工模块 |
| 2 | 员工的资产坐标 | 员工纳入 045 资产中心：`asset_type` 扩展 `employee`，四徽标（评级/上架/申领/在用）语义沿用；信任评级（036）对员工生效 | capability_assets |
| 3 | 会话绑定 | 会话创建可声明 `employee_id`；声明后该会话的能力边界/知识库/记忆 scope/模型配置按员工档案注入；**未声明员工的会话行为完全不变**（零回归硬约束） | chat-api 会话创建 |
| 4 | 可见性 | 沿用 049 口径："我的 ∪ 我参与的"（创建者 + `member_user_ids`），部门过滤复用既有组织树；跨租户 fail-closed | 员工查询 |
| 5 | 阶段拆分 | **B1**：员工 CRUD + 档案组装 + 会话绑定 + 资产中心/门户可见；**B2**：员工模板上架（依赖 053）+ IM 渠道-员工绑定与意图路由 + 员工级 API Key | tasks 分阶段 |
| 6 | 意图路由首期口径 | B2 首期 = 渠道绑定默认员工 + 关键词/规则路由（可配）；LLM 意图分类作增强项不承诺（YAGNI，先有确定性路由） | im_gateway 扩展 |
| 7 | 成本归因 | 员工维度成本经 035 既有 `agent_id` 埋点承接（employee_id 作为 agent 归属链路），不新建计量体系 | token_usage |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 创建员工并组装档案（B1，Priority: P1）🎯 MVP

管理员创建一位"财务员工"：命名 + 岗位描述，配置能力白名单（可用工具/Skill）、挂载知识库、选择记忆 scope 与模型配置。员工出现在资产中心与门户目录，状态与评级徽标可查。

**Why this priority**: 员工实体与档案是本特性的地基，无实体则绑定/认领/路由全部无从谈起；单独交付即完成"数字员工"产品形态的最小定义。

**Independent Test**: 经管理端 API 创建员工（白名单 + 知识库 + 记忆 scope + 模型配置），断言资产中心 `capabilities/list` 含 `asset_type=employee` 条目、门户目录可见、档案字段完整可编辑。

**Acceptance Scenarios**:

1. **Given** 管理员权限，**When** 创建员工并配置档案，**Then** 员工持久化（租户隔离）、资产中心与门户可见、创建操作进审计。
2. **Given** 已创建员工，**When** 修改档案（增删白名单/知识库），**Then** 变更即时生效于后续会话、变更进审计。
3. **Given** 非创建者且非成员的用户，**When** 查询该员工，**Then** 不可见（决策 #4 fail-closed）。

---

### User Story 2 - 以员工身份发起会话（B1，Priority: P1）

用户认领员工后发起会话，会话自动带上员工档案：白名单外的工具/Skill 不可用，知识库与记忆 scope 按档案注入，模型按档案配置路由。未声明员工的会话行为不变。

**Why this priority**: 这是"员工"产生业务价值的时刻——档案不再是静态配置，而是每次会话的执行边界；也是治理口径不回退的证明。

**Independent Test**: 创建白名单仅含 Skill A 的员工 → 以该员工发起会话 → 断言 Skill A 可用、Skill B 被拒（门禁事件可查）、知识库检索命中员工挂载库；另起普通会话断言行为与改造前一致。

**Acceptance Scenarios**:

1. **Given** 会话声明 `employee_id`，**When** 会话内调用白名单外工具，**Then** 被拒且审计记录（001 门禁叠加员工边界，取交集）。
2. **Given** 员工挂载知识库 K，**When** 会话内检索，**Then** K 参与检索且引用回链正常（005 口径）。
3. **Given** 员工记忆 scope 为 project，**When** 会话沉淀记忆，**Then** 按 017 口径落对应 scope。
4. **Given** 未声明员工的会话，**When** 执行任意既有流程，**Then** 行为与改造前完全一致（零回归）。
5. **Given** 员工会话产生 token 用量，**When** 成本归集查询，**Then** 可按员工维度分组（035 `agent_id` 链路）。

---

### User Story 3 - 门户认领员工（B1，Priority: P2）

普通用户在门户浏览员工目录 → 自助认领 → 走 001 审批 → 开通后可在会话与 IM 中使用该员工。

**Why this priority**: 复用 037 门户既有申领链路，边际成本低；让"员工"触达非管理员用户，完成产品闭环。

**Independent Test**: 门户目录展示员工 → 用户提交认领 → 管理员审批通过 → 用户会话可选该员工；审批拒绝则不可用。

**Acceptance Scenarios**:

1. **Given** 已上架员工，**When** 用户认领并经审批，**Then** 员工进入用户可用列表（"我参与的"口径）。
2. **Given** 认领待审批，**When** 用户尝试以该员工发起会话，**Then** 拒绝（fail-closed）。

---

### User Story 4 - IM 渠道挂员工与意图路由（B2，Priority: P2）

一个 IM 渠道绑定多个员工；消息进入时按规则路由到对应员工（默认员工兜底），会话以该员工身份执行。

**Why this priority**: StaffDeck"一个渠道挂多员工、按意图分发"的对应形态；依赖 B1 员工实体与 053 模板（可选），故列 B2。

**Independent Test**: 渠道绑定员工 A（财务关键词）与员工 B（默认）→ 发送含财务关键词消息断言路由 A，其余路由 B；路由结果进会话 `employee_id` 与审计。

**Acceptance Scenarios**:

1. **Given** 渠道绑定多员工与路由规则，**When** 消息命中规则，**Then** 路由到对应员工、会话带 `employee_id`。
2. **Given** 消息未命中任何规则，**When** 路由，**Then** 落默认员工；无默认员工时回落既有无员工会话行为（不拒绝消息）。
3. **Given** 路由规则变更，**When** 后续消息进入，**Then** 按新规则路由（热生效，变更进审计）。

---

### Edge Cases

- **员工档案引用的资产被下线**（Skill 退役/知识库删除）：会话创建时校验引用有效性，无效引用显式报错或按策略降级（clarify 定口径），不静默使用失效资产。
- **员工停用/归档**：在途会话不中断（会话级快照档案），新会话拒绝；停用进审计。
- **白名单与 001 门禁冲突**：取交集（员工边界 ∧ 门禁放行），任一拒绝即拒绝；R4 红线恒拒不受员工档案影响。
- **同一用户认领多个员工**：会话显式选择，不做自动合并；IM 路由按渠道规则。
- **员工删除**：软删除 + 历史会话保留 employee_id 溯源（审计口径），不物理清除运行记录。
- **跨租户员工 ID 猜测**：租户隔离 fail-closed（020 口径）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 新增 `employees` 实体（租户隔离）：名称/岗位描述/能力白名单（工具 + Skill）/知识库挂载/记忆 scope/模型配置/Harness profile 引用/状态/创建者/成员列表；CRUD 全审计。
- **FR-002**: 员工能力边界 MUST 与 001 门禁取交集生效；白名单外调用 MUST 拒绝并审计；R4 红线语义 MUST NOT 被员工档案覆盖。
- **FR-003**: 会话创建 MUST 支持可选 `employee_id`；声明后档案注入（边界/知识库/记忆/模型）；未声明会话行为 MUST 零改动。
- **FR-004**: 员工 MUST 纳入 045 资产中心（`asset_type=employee`）与 037 门户目录；认领走 001 审批，未开通 MUST 不可用。
- **FR-005**: 员工可见性 MUST 为"我的 ∪ 我参与的"（049 口径），跨租户 fail-closed。
- **FR-006**: 员工维度成本 MUST 经 035 `agent_id` 归因链路可分组查询，不新建计量体系。
- **FR-007**: （B2）IM 渠道 MUST 支持绑定多员工 + 规则路由 + 默认员工兜底；路由结果 MUST 落会话 `employee_id` 与审计；无默认员工时回落既有行为。
- **FR-008**: （B2）员工模板上架与复制 MUST 经 053 广场模板机制，本特性不另建分发通道。
- **FR-009**: （B2）员工级开放 API Key MUST 复用 022 凭证体系（加密存储、明文仅显示一次），权限范围限该员工相关资源。
- **FR-010**: 员工停用/删除 MUST 不破坏在途会话与历史溯源（会话级档案快照 + 软删除）。
- **FR-011**: 员工档案变更/认领/路由规则变更 MUST 全审计（001 审计流）；管理端操作经 system_audit（宪法 III）。
- **FR-012**: 前端 MUST 中英双语（宪法 IV）：admin-web 员工管理页 + user-web 门户/会话员工选择。

### Key Entities

- **Employee**: 数字员工（档案字段见 FR-001；状态 active/disabled/archived；资产坐标 `(employee, employee_id)`）。
- **EmployeeProfile**: 档案注入快照（会话创建时物化，含边界/知识库/记忆/模型配置），在途会话不受档案变更影响。
- **EmployeeClaim**: 认领记录（用户/员工/审批状态），复用 037 申领数据结构。
- **ChannelEmployeeBinding**: 渠道-员工绑定与路由规则（B2；渠道/员工/规则/默认标记）。协议结构（T008 已定）：`{binding_id, channel, employee_id, keywords: list[str], is_default: bool, tenant_id, updated_at}`；规则求值 = 关键词列表子串命中（大小写/空白归一）+ 默认员工兜底（OQ-4），同渠道至多一条默认（fail-closed）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: B1 出口——创建"财务员工"→ 认领审批 → 以其发起会话：白名单外调用被拒、知识库命中、记忆落正确 scope、成本可按员工归因，全链路 E2E。
- **SC-002**: 零回归——未声明员工的会话与既有测试全量零修改全绿。
- **SC-003**: 治理不回退——员工边界与 001 门禁交集生效有契约测试；R4 红线不受档案影响。
- **SC-004**: B2 出口——单渠道双员工规则路由正确率 100%（确定性规则测试集）；员工级 Key 权限越界被拒。
- **SC-005**: 四概念口径文档固化——员工/岗位角色/Agent/Skill 边界在 spec 与 README 叙事中无歧义（046 教训）。

## Assumptions

- 员工不是新的执行引擎：会话仍走 DSH Runtime Host，员工只是档案注入层（DSH 钉版 train 不变）。
- 知识库挂载复用 005 既有知识库实体与权限（030 数据权限口径不回退）。
- Harness profile 引用 019 既有 profile，不新建配置体系。
- 定时任务员工归属为 B1 可选扩展（`scheduled_tasks` 增 `employee_id` 维度），不阻塞 MVP。
- 内置种子员工数量不承诺（整合方案 §6 口径）。

## 待澄清（clarify 门禁）

> **OQ 决议（2026-11-09 实现批次，按 spec 已定默认值消解并记录）**：
>
> - **OQ-1**: 四概念边界——**员工 = 可对话的组织角色（agent 会话装配单元）**，与岗位角色（人的 RBAC，006 零改动）、Agent（LLM 推理单元）、Skill（能力包）分离；员工能力边界沿用 `position_roles` 白名单范式（`AGENT_CAPABILITY_KEYS` 预留），绑定对象是 agent 会话（决策 #1 固化）。**B1 已按此实现**（`employees` 实体 + 白名单 + 会话注入）。
> - **OQ-2**: 档案引用资产失效策略——**创建/绑定即校验，引用失效 fail-closed**（`reference_invalid` 审计 denied，`_bind_session_employee`）；不降级跳过（避免半装配员工带病运行）。
> - **OQ-3**: 员工级 API Key 资源范围——**只读 + 会话**（B2 实现时限定，不含档案修改）。
> - **OQ-4**: 意图路由规则表达形态——**关键词列表 + 默认员工兜底**（确定性路由，决策 #6）；LLM 意图分类作增强项不承诺（YAGNI）。B2 实现。

- **OQ-1**: 四概念边界正式定义（员工/岗位角色/Agent/Skill）——需 ADR 级拍板，参照 046 项目维度收敛先例。
- **OQ-2**: 档案引用资产失效时的策略（创建报错 vs 降级跳过）。
- **OQ-3**: 员工级 API Key 的资源范围清单（会话/Run/定时任务？是否含档案修改——建议只读 + 会话）。
- **OQ-4**: 意图路由规则的表达形态（关键词列表 vs 正则 vs 结构化条件）与配置入口。

## 跨特性关系（被依赖方视角，双向声明）

- **与 006（position-rbac-admin）**：岗位角色零改动；员工沿用其白名单范式与 `AGENT_CAPABILITY_KEYS` 预留，二者绑定对象不同（人 vs agent 会话）——OQ-1 固化。
- **与 001（gatekeeper-governance）**：员工边界与门禁取交集，不新增治理旁路；认领审批复用 001。
- **与 045（asset-center）/037（unified-portal）**：资产坐标扩展与门户目录复用，四徽标语义不变。
- **与 017/005/019/040**：记忆 scope、知识库、Harness profile、模型配置均为引用注入，不改各特性本体。
- **与 035（cost-attribution）**：员工归因经 `agent_id` 链路，不新建维度枚举（048 教训：无写方的维度不建）。
- **与 013（multi-im-entry）**：B2 渠道-员工绑定扩展 ChannelRouter；渠道注册/启停语义不变。
- **与 053（plaza-template-distribution，本批次）**：员工模板分发依赖 053；**B1 不依赖 053，B2 模板上架依赖**。
- **与 049（project-members）**：可见性口径直接沿用。

## Non-Goals

- 不改造 006 岗位角色为 agent 实体。
- 不做员工"人格化"对话风格训练（prompt 模板由档案承载，不做微调）。
- 不做 LLM 意图分类路由首期承诺（确定性规则先行）。
- 不做员工间直接通信（协作走 052 团队模式）。
- 不承诺内置员工数量；不拷贝 StaffDeck（AGPL-3.0）代码。
- 不做移动端/桌面端新形态（ADR-7）。