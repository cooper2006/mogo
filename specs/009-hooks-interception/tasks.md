# Tasks: Hooks Interception (five-event hooks)

**Input**: Design documents from `/specs/009-hooks-interception/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 钩子超时默认 **5s**（`hook_timeout_seconds` 可配），复用 `execution_timeout.ExecutionTimeoutPolicy` 模式。
- 超时/异常/规则解析失败**一律 fail_closed**（不可配置放行）；仅 observe 规则可配"只记录不拦截"。
- **首期仅 PreToolUse** 单事件；其余按节奏补齐。
- 规则 schema：`hook_rules{scope ∈ {tool,session,tenant}, rule_type ∈ {deny_tool,require_field,observe}, rule_config, enabled}`。
- 非红线钩子可被 019 薄模式跳过；fail_closed 底线保留。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/dsh_runtime/hooks/`（新子模块）+ hook_rules 管理端点。挂载点 = `turn_admission.admit_skill_selection`（PreToolUse 天然切入）。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 `services/chat-api/app/dsh_runtime/hooks/__init__.py` + 子模块骨架（registry/engine/rules/timeout/integration）
- [x] T002 实现 `rules.py`：声明式规则 schema（`hook_rules{scope, rule_type, rule_config, enabled}`）+ 校验
- [x] T003 实现 `registry.py`：五事件注册/查找（SessionStart/PreToolUse/PostToolUse/SessionEnd/MemoryCommit；首期仅启用 PreToolUse）

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T004 [P] 实现 `timeout.py`：超时保护（默认 5s，复用 `ExecutionTimeoutPolicy` 模式）+ fail_closed（超时/异常/解析失败均拒绝，不可配放行）
- [x] T005 [P] 实现 `engine.py` 规则求值核心：先按作用域（工具>会话>租户）再按类型（deny>require>observe），deny 命中短路

## Phase 3: User Story 1 (P1) — PreToolUse 声明式规则（首期核心）

**Goal**: deny_tool / require_field / observe 三类规则生效；规则变更即时生效。
**独立测试**: deny 命中拒绝（403，与门禁拒绝区分）；require_field 缺字段拒绝；observe 只记录不拦截。

- [x] T006 实现 deny_tool 规则求值 + 拒绝返回（403 + "被钩子规则拒绝"提示，与门禁拒绝区分）
- [x] T007 实现 require_field 规则求值（请求缺必填字段 → 拒绝）
- [x] T008 实现 observe 规则（仅记录，不改拦截结果）
- [x] T009 实现 `integration.py`：挂载 PreToolUse 到 `turn_admission.admit_skill_selection`（工具调用前求值）
- [x] T010 US1 测试：三类规则 Acceptance + 规则即时生效

## Phase 4: User Story 2 (P2) — 钩子审计与可观测

**Goal**: 钩子执行事件进 001 审计落点；执行可追溯。
**独立测试**: 每次钩子求值 → 审计记录（身份/工具/结果/时间戳）。

- [x] T011 实现钩子执行审计（进 001 审计落点，复用既有 `governance/audit.py`；含通过/拒绝 + 规则命中）
- [x] T012 US2 测试：钩子执行 100% 进审计

## Phase 5: User Story 3 (P2) — 会话生命周期钩子（SessionStart/End/MemoryCommit）

**Goal**: 三类会话事件钩子与 002 联动。
**独立测试**: SessionStart 可注入初始上下文；SessionEnd 可清理；MemoryCommit 可过滤待提交记忆。

- [x] T013 实现 SessionStart/PostToolUse/SessionEnd/MemoryCommit 钩子（与 002 会话事件联动）
- [x] T014 US3 测试：四事件触发 + 可携带数据正确（FR-12）

## Phase 6: User Story 4 (P2) — 钩子规则管理

**Goal**: 声明式配置增删规则无需改代码；规则 CRUD 端点。
**独立测试**: 新增/停用规则即时生效；无代码改动。

- [x] T015 实现 hook_rules CRUD 管理端点（声明式配置，即时生效）
- [x] T016 实现规则作用域查询（tool/session/tenant 三级匹配）

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T017 [P] fail_closed 自检：超时/异常/解析失败 100% 拒绝（无越权放行，Success 基准）
- [x] T018 [P] 钩子延迟预算守护：单次工具调用钩子总延迟 ≤ 5s（多钩子共享预算，超限 fail_closed，FR-13）
- [x] T019 写 `quickstart.md` + `contracts/hooks.md`（五事件 IO 契约 + 规则 schema）

---

## Dependencies

```text
Phase 1 (骨架/规则 schema/注册) → Phase 2 (超时/fail_closed/求值核心) → US1 → US2 → US3 → US4 → Polish
关键: T005 求值核心被全故事复用；T004 fail_closed 是底线（不可绕过）
```

## Parallel Opportunities
- T004/T005（Phase 2）可并行
- US1 完成后，US2（审计）/US4（管理端点）可部分并行

## MVP Scope
- **最小 = Phase 1 + Phase 2 + US1**（T001–T010）：PreToolUse 三类规则跑通 + fail_closed 底线 + 挂载 `turn_admission`，即合规拦截可用（首期核心）。
- 增量：US2（审计）→ US3（会话事件）→ US4（管理端点）。

## Notes
- 首期仅 PreToolUse（最小代价获合规拦截）；五事件为目标态。
- 与 001（扩展点+审计落点）、002（会话事件载体）、010（节点触发）、019（非红线可跳）的跨特性关系已在 spec 双向声明。
- 未改 services 源码；本文件仅在 `specs/009-hooks-interception/` 下。
