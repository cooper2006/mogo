# Tasks: Unified Six-Layer Gatekeeper (Governance & Risk Control)

**Input**: Design documents from `/specs/001-gatekeeper-governance/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 审批层复用 `chat-api/enterprise_capabilities/tools/approval_runtime` + `approval_events` 的 `EnterpriseApproval` 状态机，**不新建审批表**；恢复 = poll，超时 5min。
- 配额用 **MongoDB**（`quota_counters` 集合，原子 findOneAndUpdate），不引入 Redis。
- PII = 全局默认策略（手机号 mask / 私钥 remove / 身份证 hash / 银行卡 mask / 邮箱 abstract）+ 租户级可覆盖。
- 注：plan 第 89 行"如不存在则新增 approval_requests 表"以 clarify OQ-1 为准——**不新建审批表**，复用既有 `approval_runtime`。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

---

## Phase 1: Setup (Project Initialization)

**Goal**: 搭建 governance 模块骨架与配置基座，为所有故事提供共同入口。

- [x] T001 创建 `services/admin-api/app/governance/__init__.py` 包骨架（导出 gatekeeper 入口 + 各 layer 注册点）
- [x] T002 创建 `services/admin-api/app/governance/config.py`：声明式配置 schema（门禁层增删、启用顺序、审计开关），支持"默认厚模式 + 显式降级"
- [x] T003 创建 `services/admin-api/app/governance/layers/__init__.py` + 各层文件占位（identity/rbac/redaction/approval/quota/audit），定义统一 `GateLayer` 协议（`evaluate(ctx) -> GateVerdict`）
- [x] T004 定义 `GateContext` / `GateVerdict` 数据类（`services/admin-api/app/governance/gatekeeper.py`）：调用主体、工具、风险级、自主级别、逐层结果、短路原因
- [x] T005 实现 `gatekeeper.evaluate(tool, ctx)` 六层串行编排 + 任一层拒绝即短路 + 拒绝原因落审计（串联 T002 配置 + T003 各层）
- [x] T006 在 `services/admin-api/app/api/routes/tools.py` 工具调用入口注入 `gatekeeper.evaluate`（被拒返回 403/429/409，审批挂起 409 + 审批 token）

---

## Phase 2: Foundational (Blocking Prerequisites for All Stories)

**Goal**: 建立被所有用户故事依赖的基础设施（数据表、审计落点、权限码模型）。

- [x] T007 [P] 创建新表/集合 DDL：`gatekeeper_rules`、`risk_tiers`、`autonomy_matrix`、`pii_policies`、`quota_counters`、`gate_events`（`services/admin-api/app/governance/` 建表脚本）
- [x] T008 [P] 实现审计落点：`gate_events` 写入路径复用 `system_audit/repository.py`（单一审计落点，含层号/风险级/自主级别/时间戳）
- [x] T009 [P] 实现 `rbac_model.py`：权限码 `<resource>:<action>[:<target>]` 解析 + 三级隔离（租户/组织/用户）+ 未知码 fail-closed + `expand_role_to_codes(role)`（岗位角色 → 权限码预设组，对接 `position_roles/service.py`）

---

## Phase 3: User Story 1 (P1) — 工具调用必须经过六层串行门禁

**Goal**: 打通"身份→RBAC→脱敏→审批→配额→审计"完整链，任一层短路。
**独立测试**: 无权限调用 → 第 2 层拒绝；全流程通过 → 六层全过 + 审计记录。

- [x] T010 实现 `layers/identity.py`（层 1：解析调用主体 = 租户/用户/岗位角色）
- [x] T011 实现 `layers/rbac.py`（层 2：权限码判定，复用 T009 `rbac_model`，fail-closed）
- [x] T012 实现 `layers/audit.py`（层 6：通过/拒绝事件落 `gate_events`，含层号/风险级/自主级别/时间戳）
- [x] T013 串联 US1 三层（identity→rbac→audit）到 `gatekeeper.evaluate`，写六层链集成测试（无权限短路 + 全通过路径）
- [x] T014 补 US1 其余三层占位接入（redaction/approval/quota 由后续故事实现，US1 先以 pass-through 占位保证链路完整）

---

## Phase 4: User Story 2 (P1) — R0–R4 风险分级 + L1–L5 自主级别矩阵

**Goal**: 生成并维护 25 格 `AUTONOMY_MATRIX[L][R]`，R4 在 L5 仍 deny。
**独立测试**: L3×R2→require_approval；L5×R4→deny（不可覆盖）；R0 任意 L→allow。

- [x] T015 [P] 实现 `risk.py`：R0–R4 工具风险分级注册（`risk_tiers` 表）
- [x] T016 [P] 实现 `AUTONOMY_MATRIX`（25 格，`autonomy_matrix` 表）：`[L][R] -> allow/require_approval/deny`，含"R4 任意 L = deny、管理员不可覆盖"规则
- [x] T017 矩阵单元测试：断言 L3×R2=require_approval、L5×R4=deny、R0 全 L=allow 三组 Acceptance
- [x] T018 实现 `api/routes.py` 矩阵/风险分级 CRUD 端点（管理面维护矩阵 + 工具风险级）

---

## Phase 5: User Story 3 (P2) — PII 脱敏层

**Goal**: 请求/响应文本按策略脱敏，审计只存脱敏值 + 哈希指纹。
**独立测试**: 手机号→mask；私钥→remove（不出现在工具请求体）；审计 0 明文 PII。

- [x] T019 [P] 实现 `pii.py`：正则识别器（私钥/身份证/银行卡/手机号/邮箱 5 类）+ 策略引擎（mask/remove/hash/abstract）
- [x] T020 [P] 实现 PII 策略表 `pii_policies`：全局默认（手机号 mask/私钥 remove/身份证 hash/银行卡 mask/邮箱 abstract）+ 租户级可覆盖（覆盖需 006 授权 + 001 审计）
- [x] T021 实现 `layers/redaction.py`（层 3：请求/响应文本脱敏，作用文本不改工具执行语义）
- [x] T022 PII 单测：5 类 PII × 4 策略矩阵 + 审计 0 明文断言（验收：手机号 mask / 私钥 remove）

---

## Phase 6: User Story 4 (P2) — 细粒度 RBAC 权限码模型

**Goal**: 权限码三级隔离 + 岗位角色预设组向下兼容。
**独立测试**: 持 `knowledge:read` 可读；无权限调 `admin:role:assign` 拒绝；岗位角色变更即时生效。

- [x] T023 [P] 扩展 `rbac_model.py`：权限码三级隔离（租户/组织/用户）+ 岗位角色预设组映射（复用 T009）
- [x] T024 实现权限码管理端点（`api/routes.py`：创建/授权/回收权限码，变更即时生效 + 审计）
- [x] T025 US4 集成测试：Acceptance 三组（knowledge:read 通过 / admin:role:assign 无码拒绝 / 岗位角色绑定预设组生效）

---

## Phase 7: User Story 5 (P3) — 配额三维计量

**Goal**: 租户/用户/工具三维配额，超限拒绝并提示维度。
**独立测试**: 租户日配额 1000，第 1001 次拒绝（提示租户）；工具配额 10/h 触发仅该工具受限。

- [x] T026 [P] 实现 `quota.py` + `quota_counters`（MongoDB 原子 findOneAndUpdate，三维 = 租户/用户/工具，时间窗口 min/day/month，不引入 Redis）
- [x] T027 实现 `layers/quota.py`（层 5：超限拒绝 + 返回超限维度）
- [x] T028 US5 集成测试：租户日配额触发 + 单工具配额独立触发两组 Acceptance

---

## Phase 8: Polish & Cross-Cutting Concerns

**Goal**: 观测性、性能、配置化收尾。

- [x] T029 [P] 门禁链性能验证：单次 evaluate p95 < 15ms（不含审批等待），审计落库异步（性能目标断言）
- [x] T030 [P] 声明式配置收尾：`config.py` 支持增删门禁层无需改代码 + 配置变更留审计（FR-10）
- [x] T031 审计覆盖率自检：全链路工具调用 100% 经门禁 + 100% 落 `gate_events`（Success Criteria 总验收）
- [x] T032 写 `quickstart.md`（门禁启用 + 各故事验证步骤）+ `contracts/gatekeeper.md`（六层 IO 契约 + 25 格矩阵定义）

---

## Dependencies

```text
Phase 1 (骨架/配置/协议/编排) → Phase 2 (基础表/审计/权限码模型)
Phase 2 → US1(T010-014) → US2(T015-018) → US3(T019-022) → US4(T023-025) → US5(T026-028)
US1-5 各阶段 → Phase 8 (Polish)
关键依赖: T009 rbac_model 被 US1/US4 复用；T007 建表阻塞所有数据层任务
```

## Parallel Opportunities
- T007/T008/T009（Phase 2）互不依赖，可并行
- 各 US 内 [P] 标记任务（T015/T016、T019/T020、T023、T026）可并行
- 故事间按 P1→P2→P3 顺序推进，US1/US2 完成后再并行 US3/US4/US5

## MVP Scope
- **最小可交付 = Phase 1 + Phase 2 + US1**（T001–T014）：六层链跑通 + 基础表 + 审计 + 权限码，即可让工具调用过门禁（redaction/approval/quota 先 pass-through 占位）。
- 增量交付：US2（矩阵）→ US3（脱敏）→ US4（权限码管理）→ US5（配额）。

## Implementation Strategy
- 先 MVP（US1 跑通全链路，其余层占位），再逐故事填充各层真实实现
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 审批层（US1 占位 → 实际复用 `approval_runtime`）在 US2/US3 之间落地为对既有 `ApprovalRuntime` 的封装（poll + 5min 超时）
- 测试基准 = spec Acceptance Scenarios + `checklists/requirements.md` 已勾选需求项

## Notes
- 本 tasks.md 为 `/speckit-tasks` 产出，含 001 的 clarify 决策（复用审批/不建表、MongoDB 配额、PII 全局默认+租户覆盖）。
- 实现需先通过 `checklists/requirements.md` 门禁（未勾选需求项须先消解）。
- 未改 services 源码；本文件仅在 `specs/001-gatekeeper-governance/` 下。
