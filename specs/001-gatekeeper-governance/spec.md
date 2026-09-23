# Feature Specification: Unified Six-Layer Gatekeeper (Governance & Risk Control)

**Feature Branch**: `001-gatekeeper-governance`

**Created**: 2026-07-08

**Status**: Draft

**Input**: Unified six-layer gatekeeper: identity, RBAC, PII redaction, approval, quota, audit; R0–R4 tool risk tiers and autonomy matrix (L1–L5 × R0–R4, 25 cells)

## User Scenarios & Testing *(mandatory)*

以下用户故事按优先级排列，每个都是可独立交付、可独立测试的垂直切片。

### User Story 1 (P1) — 工具调用必须经过六层串行门禁

管理面或运行时的每一次工具调用（tool invocation）都按固定顺序经过六层门禁链：

1. **身份（Identity）** — 调用主体是谁（租户/用户/岗位角色）
2. **RBAC** — 主体是否持有目标工具的 `<resource>:<action>[:<target>]` 权限码，无权限则 fail-closed
3. **脱敏（PII Redaction）** — 请求/响应文本按策略 mask/remove/hash/abstract 处理
4. **审批（Approval）** — 高自主级别 × 高风险级的组合必须人工审批通过才放行
5. **配额（Quota）** — 租户/用户/工具三维配额，超限拒绝
6. **审计（Audit）** — 通过/拒绝事件全部落审计日志，含门禁层号、风险级、自主级别

若任一层拒绝，后续层不再执行（短路），拒绝原因写入审计。

**Acceptance Scenarios:**
- 无权限用户调用工具 → 第 2 层拒绝，审计记录 RBAC 拒绝
- 高自主级别 + R3 风险工具 → 第 4 层挂起等待审批，审批通过后才执行
- 配额耗尽 → 第 5 层拒绝，返回明确的配额错误
- 六层全部通过 → 工具执行，第 6 层记录成功

### User Story 2 (P1) — R0–R4 风险分级 + L1–L5 自主级别矩阵

- 每个工具在注册时标注风险级 R0（只读无影响）到 R4（红线不可逆）
- 每个执行上下文有自主级别 L1（全人工）到 L5（全自动）
- 生成 25 格矩阵：`AUTONOMY_MATRIX[L][R]` → 动作（allow / require_approval / deny）
- R4 工具在 L5 下仍为 deny（红线不可覆盖，constitution 原则 II）

**Acceptance Scenarios:**
- L3 × R2 → require_approval
- L5 × R4 → deny（不可被管理员覆盖为 allow）
- R0 工具在任何 L 级别 → allow（只读无需审批）

### User Story 3 (P2) — PII 脱敏层

- 请求/响应文本中的 PII（私钥、身份证号、银行卡号、手机号等）按配置策略脱敏
- 策略四选一：mask / remove / hash / abstract，按 PII 类型分别配置
- 脱敏结果保留可追溯（哈希可对照原始值做审计，不存明文）

**Acceptance Scenarios:**
- 含手机号的用户消息 → 默认 mask 策略下展示为 138****0000
- 私有密钥字段 → 默认 remove 策略下不出现在工具请求体
- 审计日志中只存脱敏后的值与哈希指纹

### User Story 4 (P2) — 细粒度 RBAC 权限码模型

- 权限码格式：`<resource>:<action>[:<target>]`，如 `knowledge:read`、`admin:role:assign`
- 三级隔离：租户级 / 组织级 / 用户级
- 未知权限码 → fail-closed 拒绝
- 现有"岗位角色"粗粒度权限作为权限码集合的预设组，保持向下兼容

**Acceptance Scenarios:**
- 持有 `knowledge:read` 的租户用户可读取知识条目
- 不持有任何权限码调用 `admin:role:assign` → 拒绝
- 岗位角色"工程师"绑定预设权限码组，权限变更即时生效

### User Story 5 (P3) — 配额三维计量

- 配额维度：租户 / 用户 / 工具，各自独立配置上限
- 超限时第 5 层拒绝并返回哪个维度超限
- 配额支持时间窗口（每分钟/每天/每月）

**Acceptance Scenarios:**
- 租户日配额 1000 次工具调用，第 1001 次 → 拒绝，提示租户配额
- 某工具单独配额 10 次/小时，触发后仅该工具受限

### Notes / Assumptions
- 本特性补齐 docs/MOVO企业级智能体功能补强规划.md 中"二、GAP 分析 2.1 治理与风控层"
- 六层门禁为串行链，任一层可短路
- R4 红线工具在任何自主级别下均 deny，不可被管理员覆盖
- 脱敏层作用于请求/响应文本，不改变工具执行语义
- 权限码模型与现有岗位角色系统共存，岗位角色是权限码的预设组
- 不实现 LLM 网关韧性（属特性 002）、DAG 编排（属特性 003）

## Functional Requirements

- FR-1: 工具调用必须经过六层串行门禁链（身份→RBAC→脱敏→审批→配额→审计），任一层拒绝则短路并审计
- FR-2: 工具注册时标注风险级 R0–R4，执行上下文有自主级别 L1–L5
- FR-3: 生成并维护 25 格 `AUTONOMY_MATRIX[L][R]`，值为 allow/require_approval/deny
- FR-4: R4 工具在 L5 下仍为 deny，管理员不可覆盖红线
- FR-5: 权限码模型 `<resource>:<action>[:<target>]`，三级隔离（租户/组织/用户），未知权限码 fail-closed
- FR-6: 现有岗位角色作为权限码预设组，向下兼容
- FR-7: PII 脱敏按类型配置策略（mask/remove/hash/abstract），审计只存脱敏值与哈希指纹
- FR-8: 配额三维（租户/用户/工具）独立配置，超限返回明确维度提示
- FR-9: 所有门禁通过/拒绝事件落审计日志，含层号、风险级、自主级别、时间戳
- FR-10: 门禁链可通过声明式配置增删层，无需改代码（扩展点）

## Non-Goals
- 不实现 LLM 网关韧性、failover、degradation_chain（属特性 002）
- 不实现 DAG 通用编排、拓扑排序、环检测（属特性 003）
- 不实现自进化 / Dream Cycle（属特性 004）
- 不实现会话级版本化 / 交接 / 协同（属特性 005）
- 不改变现有 DSH 运行时 Agent 执行语义，仅加治理层

## Success Criteria
- 工具调用 100% 经过门禁链，审计覆盖率 100%
- R4 红线工具在 L5 下拒绝率 100%
- 配额超限 100% 触发第 5 层拒绝
- PII 字段 100% 按策略脱敏，审计日志 0 明文 PII
- 权限码模型支持至少 10 个 resource × 3 个 action 的权限码

## Further Details
- 技术实现由 plan.md 承载
- 与现有 admin-api system_audit、enterprise_capabilities 模块的集成方式见 plan.md

## Clarify 记录（/speckit-clarify，2026-07-08）

### OQ-1 审批流程（spec 原 OQ-1）
- **决策**：复用 `chat-api/enterprise_capabilities/tools/approval_runtime` + `approval_events` 的既有审批状态机（`EnterpriseApproval` 含 risk_level/scope_label/status），**不新建审批流程表**。
- **恢复机制**：**poll**（前端轮询 `list_pending`/`decide`），非 callback。`ApprovalRuntime.validate_and_consume` 是"校验并消费"语义，挂起方需主动 poll 取 ticket 结果。
- **超时**：审批挂起默认 5 分钟（与 019 厚度配置的审计/超时底线对齐，可配置）。
- **影响**：plan.md 的"审批挂起"层实现为对既有 `ApprovalRuntime` 的封装，`gatekeeper.py` 层 4 不另起炉灶。

### OQ-2 配额存储（spec 原 OQ-2）
- **决策**：配额计量**用数据库（MongoDB）**，不引入 Redis 计数。理由：自托管形态（movo 交付）已依赖 MongoDB，引入 Redis 仅做计数会增加运维负担；配额上限低（租户/用户/工具三维，时间窗口计数），MongoDB 计数器（原子 `findOneAndUpdate`）足够。
- **影响**：`quota.py` 层 5 落 `quota_counters` 集合（按 维度 + 时间窗口 键），不依赖 Redis。

### OQ-3 PII 策略粒度（spec 原 OQ-3）
- **决策**：PII 策略**默认全局固定**（手机号 mask / 私钥 remove / 身份证 hash / 银行卡 mask / 邮箱 abstract），**租户级可覆盖**（白名单 + 策略改配走 006 RBAC 授权 + 001 审计）。即"全局默认 + 租户可选覆盖"，非纯全局或纯租户。
- **影响**：`pii.py` 内置默认策略表；租户覆盖经 `pii_policies` 集合 + 授权门禁。

