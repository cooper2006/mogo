# Tasks: DAG Orchestration Engine (four modes)

**Input**: Design documents from `/specs/010-dag-orchestration-engine/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 条件表达式 = **JSON 条件对象**（`==`/`!=`/`>`/`>=`/`<`/`<=`/`and`/`or`/`not`/`in`/`has`），**禁用任意代码 AST**。
- 无依赖并行**默认并发度 4**（`dag_max_concurrency` 可配），超限排队。
- 节点重试**分层**：007 做模型调用级重试，010 做节点级重试（节点重试包裹 007，不重复退避）。
- 迁移策略 = **双轨并行 + 等价测试**（新编排走 DAG，旧场景保留至等价验证通过）。
- 表达式语法错误默认 **fail_closed**（跳过 + 审计），可配报错中断。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/orchestration/`（新模块）；既有 `enterprise_capabilities/content/planning/` 作迁移验证场景。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 `services/chat-api/app/orchestration/__init__.py` + 子模块骨架（graph/topo/engine/conditions/retry/registry）
- [x] T002 实现 `graph.py`：DAG 节点/边模型（节点数据传递 = 上游输出写共享上下文，下游按 key 读取）
- [x] T003 实现 `registry.py`：编排定义声明式管理（节点/边/条件/重试 + `version` 版本字段）

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T004 [P] 实现 `topo.py`：拓扑排序 + 环检测（环报错含环路径，格式 = 节点 ID 序列 `A → B → C → A`）
- [x] T005 [P] 实现 `conditions.py`：JSON 条件对象求值器（受限算子，禁任意代码）+ 语法错误 fail_closed（跳过 + 审计）

## Phase 3: User Story 1 (P1) — graph 模式执行（拓扑 + 并行）

**Goal**: graph 模式按拓扑执行，无依赖节点并行（并发度 4），节点失败阻塞下游闭包。
**独立测试**: 拓扑顺序正确；无依赖并行≤4；节点失败 → 全下游闭包 blocked。

- [x] T006 实现 `engine.py` graph 模式执行器（拓扑调度 + 并发度 4 + 超限排队）
- [x] T007 实现节点失败阻塞（全传递下游闭包标记 `blocked`，区别于 `failed`）
- [x] T008 实现节点执行事件审计（启动/完成/失败/跳过/重试）
- [x] T009 US1 测试：拓扑正确 + 并行度 + 阻塞闭包三组 Acceptance

## Phase 4: User Story 2 (P1) — 四模式（sequential / supervisor / hybrid）

**Goal**: 四种编排模式全部可执行；supervisor 分派/聚合 + 失败传播。
**独立测试**: 四模式各跑通；supervisor 监督失败/子全失败传播正确。

- [x] T010 实现 sequential / hybrid 模式执行器
- [x] T011 实现 supervisor 模式（监督节点分派子节点 + 聚合结果 + 失败传播：监督失败→整体失败，子全失败→监督失败，阈值可配）
- [x] T012 US2 测试：四模式执行 + supervisor 失败传播

## Phase 5: User Story 3 (P2) — 条件跳过

**Goal**: 节点按 JSON 条件跳过；跳过可追溯。
**独立测试**: 条件真 → 跳过；条件假 → 执行；语法错误 → fail_closed 跳过 + 审计。

- [ ] T013 接入条件跳过（编排执行到节点时求值，真则跳过 + 可选下游处理）
- [ ] T014 实现跳过追溯（跳过原因 = 求值结果 + 被跳过的下游标记）
- [ ] T015 US3 测试：条件真/假/语法错误三组 Acceptance

## Phase 6: User Story 4 (P2) — 节点级重试

**Goal**: 节点失败按指数退避重试（分层于 007 模型重试）。
**独立测试**: 节点失败重试至成功/上限；重试次数/退避可配；包裹 007 模型重试不重复。

- [ ] T016 实现 `retry.py` 节点级 exponential backoff（次数/退避可配；调用上游 007 韧性调度器，不重复模型退避）
- [ ] T017 US4 测试：节点重试生效 + 分层不重复

## Phase 7: User Story 5 (P2) — 内容规划迁移（双轨 + 等价）

**Goal**: 既有 content/planning 迁移到 DAG 引擎，行为等价。
**独立测试**: 等价测试通过；旧场景保留可用（双轨）。

- [ ] T018 迁移 `enterprise_capabilities/content/planning/builder.py` 的 semantic/structured/fallback 路径到 DAG（双轨）
- [ ] T019 等价测试：新旧路径输出一致（回归 0 破坏）

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T020 [P] 跨层并发预算守护：多 DAG 并行受 007 网关配合（超限退避排队，FR-12）
- [ ] T021 [P] 编排定义版本化：契约版本递增，旧版可回看
- [ ] T022 写 `quickstart.md` + `contracts/orchestration.md`（编排定义 schema + 四模式契约）

---

## Dependencies

```text
Phase 1 (骨架/图模型/注册) → Phase 2 (拓扑/条件) → US1 → US2 → US3 → US4 → US5 → Polish
关键: T004 拓扑 + T005 条件是 US1-3 前置；T016 节点重试依赖 007 韧性调度器
```

## Parallel Opportunities
- T004/T005（Phase 2）可并行
- US3（条件）/US4（重试）可在 US1 完成后并行；US5（迁移）独立推进

## MVP Scope
- **最小 = Phase 1 + Phase 2 + US1**（T001–T009）：graph 模式拓扑执行 + 并行 + 阻塞，即通用 DAG 引擎核心可用。
- 增量：US2（四模式）→ US3（条件）→ US4（重试）→ US5（迁移）。

## Notes
- 引擎不绑定内容语义；`content/planning` 作迁移验证场景（双轨 + 等价）。
- 与 007（重试分层）、009（节点钩子触发）、002（版本化对接）的跨特性关系已在 spec 双向声明。
- 未改 services 源码；本文件仅在 `specs/010-dag-orchestration-engine/` 下。
