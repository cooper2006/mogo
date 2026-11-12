# Tasks: 审批单一内核（056-unified-approval-kernel）

**Input**: Design documents from `/specs/056-unified-approval-kernel/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **架构治理类特性**——无新业务功能引入，属既有三套审批状态机的结构性合并。影响面为三个服务的调用方接口，API 契约零变化。

**Tests**: `tests/test_approval_kernel.py`、`tests/test_approval_kernel_concurrency.py`、`tests/orchestration/` 全量回归（基准 207 passed）。

**Organization**: Phase 0 研究与澄清 → Phase 1 类型骨架 → Phase 2 核心实现 → Phase 3 审计汇接 → Phase 4 改派出口 → Phase 5 身份校验 → Phase 6 旧代码迁移 → Phase 7 验收与文档。任务编号 T001 起连续。

---

## Phase 0: 研究与澄清

- [ ] T001 建立 spec/plan/tasks/checklist 四件套（`specs/056-unified-approval-kernel/`，本文件）
- [ ] T002 `/speckit-clarify` 消解 D1/D2/D3：存量数据迁移策略、改派通知渠道、resume_token 重签语义；决策回填 spec「Clarify Decisions」节
- [ ] T003 核实 `services/admin-api/app/governance/layers/approval.py` 中所有 `ApprovalRegistry` 的生产调用点（grep 全仓），列出需改造的函数清单
- [ ] T004 核实 `services/chat-api/app/services/portal/requests.py` 中 `approve()` / `deny()` 的生产调用路径与 audit 写入位置

## Phase 1: 设计 + 类型骨架

- [ ] T005 在 `specs/056-unified-approval-kernel/plan.md` 中细化 Phase 1–7 的各步骤边界与文件清单
- [ ] T006 [P] 新建 `services/chat-api/app/governance/approval_kernel_types.py`：定义 `ApprovalState`（Enum）、`ApprovalSource`（Enum）、`ApprovalTicket`（frozen dataclass）、`ApprovalOutcome`（frozen dataclass）、`ApprovalTodo`（dataclass）、`ApprovalConflictError`（Exception）
- [ ] T007 [P] 在 `tests/fixtures/` 下新建 `fake_approval_collection.py`：InMemory 集合，支持 `find_one_and_update` with `$inc revision`、`update_one` with filter、`insert_one`、`count_documents`
- [ ] T008 在 `services/chat-api/app/governance/approval_kernel.py` 创建 `ApprovalKernel` 类骨架（方法签名全为 `pass` + docstring），接入 fake collection
- [ ] T009 写 stub 单测 `tests/test_approval_kernel_stub.py`：各 method 调 pass 不抛异常，确保 Phase 2 起点干净

## Phase 2: 核心实现（issue / decide / cancel / list_todos）

- [ ] T010 [P] 实现 `issue()`：`find_one_and_update` upsert，初始状态 `pending`，生成 32-hex token，写入 `gate_approvals` 兼容 schema（`action_id` / `token_hash` / `status` / `approver_id` / `deadline` / `revision:0`）
- [ ] T011 [P] 实现 `decide()`：`update_one` filter = `{_id, status: "pending", revision: expected_revision}`；成功后按 `source` 分发回调 hook（tool/portal/sop 三种）
- [ ] T012 [P] 实现 `cancel()`：`update_one` filter = `{source_id, status: "pending"}`；成功后清空待办、写 `approval.cancelled` 事件
- [ ] T013 [P] 实现 `list_todos()`：`find` 聚合查询，按 `approver_id` 过滤，返回统一视图（含 `source_type` / `source_id` 字段）
- [ ] T014 集成测试：起 Mongo fake db，端到端走完 issue→decide→list / issue→cancel→list 生命周期，断言状态转换正确、事件已落
- [ ] T015 [P] 并发单测：100 次并发 cancel vs decide 竞态，断言 0 次双重生效或状态回退
- [ ] T016 [P] 并发单测：两并行审批节点 A/B，A 驳回时断言 B 立即 expire（不等待 B 决策）

## Phase 3: 审计汇接（R-6 / P1-3）

- [ ] T017 [P] 在 `issue()` / `decide()` / `cancel()` 内部加入 `audit_event()` 调用，用 `build_event()` 构造事件（`source_service="chat-api"`，action 前缀 `approval.{source}.{action}`）
- [ ] T018 [P] 在 `reassign()`（Phase 4 预置）和 `resolve_timeout()`（Phase 4）内加入同等审计调用
- [ ] T019 mock audit_repo 测试：断言每次 kernel 操作产生且仅产生一条 gate_events 记录，字段完整（action/actor_id/tenant_id/source_type）
- [ ] T020 审计写入失败降级测试：mock audit_repo 抛异常，断言 kernel 继续执行（fail-open 降级与 001 口径一致），错误被记入 application log

## Phase 4: 改派出口补齐（R-4 / P1-4）

- [ ] T021 [P] 实现 `reassign()`：原子更新 `approver_id` + `deadline` + 重签 `resume_token` + `$inc revision`
- [ ] T022 [P] 修改 `services/chat-api/app/api/endpoints/orchestration_runs.py` 的 `resolve_review` 端点：action 白名单由 `("skip","terminate")` 扩展为 `("skip","terminate","reassign")`，调用 Kernel.reassign()
- [ ] T023 并发改派+决策竞态测试：同一节点先 reassign 后 decide，断言 decide 作用于新 approver；反向顺序同样断言正确
- [ ] T024 [P] 新增 `approval.timeout.expire` 事件类型（用于多分支场景中单分支驳回导致其他分支 expire 的情形）

## Phase 5: 身份一致性校验（R-5 / P1-1）

- [ ] T025 [P] `decide()` 增加 `actor_id == approver_id` 校验；不等时返回 `ApprovalOutcome(rejected=True, reason_code="approval.actor_mismatch")`
- [ ] T026 [P] admin-api 决策端点加 RBAC 守卫（需 `approval:decide` 权限码）
- [ ] T027 测试：actor_mismatch 场景返回 403；正常路径返回 200
- [ ] T028 [P] 角色型审批人暂记 warning log + skip（D1 clarify 结果：首期仅用户型），后续二期支持

## Phase 6: 旧代码迁移与清理

- [ ] T029 [P] 改造 `admin-api/app/governance/layers/approval.py:ApprovalRegistry.decide()` 内部调 `ApprovalKernel.decide(source=ApprovalSource.TOOL,...)`，保留旧签名作为 deprecated shim
- [ ] T030 [P] 改造 `chat-api/app/orchestration/human_approval.py:human_decide()` 内部调 `ApprovalKernel.decide(source=ApprovalSource.SOP,...)`
- [ ] T031 [P] 改造 `chat-api/app/services/portal/requests.py:PortalRequestService.approve()` 内部调 `ApprovalKernel.decide(source=ApprovalSource.PORTAL,...)`
- [ ] T032 grep 全仓验证：`grep -rn "ApprovalRegistry\|validate_and_consume" services/ --include="*.py" | grep -v test | grep -v __pycache__` 结果仅保留 deprecated shim 注释行，无实际生产引用
- [ ] T033 删除 `ApprovalRegistry.validate_and_consume()` 的实现体（留空 shim 供外部不可见的历史调用兜底）

## Phase 7: 验收与文档

- [ ] T034 跑 `tests/orchestration/` 全量，目标 ≥ 207 passed（维持接线会话基线）
- [ ] T035 跑 `tests/admin-api/test_approval*` 全量
- [ ] T036 跑 `tests/chat-api/test_portal*` 全量
- [ ] T037 更新 `specs/INDEX.md`：新增 056 特性条目 + SDD 路径段「审批单一内核」
- [ ] T038 更新 `CHANGELOG.md`（056 条目 + 改动文件清单）
- [ ] T039 更新 `contracts/orchestration.md` §R-19：补充 approval_kernel 路由说明
