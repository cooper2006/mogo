# Tasks: Harness Elastic Config (thick / thin)

**Input**: Design documents from `/specs/019-harness-elastic-config/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 维度优先级：**场景 > 租户 > 工具**（更具体覆盖更宽泛）。
- 薄模式可省层 = **审批（层4）+ 配额（层5）**；不可省 = **身份（层1）+ RBAC（层2）+ 脱敏（层3）+ 审计（层6）+ R4 红线**。
- 薄模式最小审计 = **身份主体 + 工具名 + 结果 + 时间戳 四元组**（底线，不可关）。
- 切换生效时机 = **工具调用级**（每次调用解析 会话+租户+工具 的 profile）。
- 019 先挂 `approval_runtime`/`audit` 过渡；001 完成后切到 001 gatekeeper；二者不阻塞。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/harness_config/`；不改变 001 六层语义。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 `services/chat-api/app/harness_config/__init__.py` + 子模块骨架（profile/layer_switch/floor/audit）
- [x] T002 实现 `profile.py`：厚度配置 schema（scope ∈ scene/tenant/tool + 启用层列表 + 审计粒度 + 超时）

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现维度优先级解析（场景 > 租户 > 工具）与 profile 合并
- [x] T004 [P] 实现 `floor.py` 底线守护：**配置侧拒绝对红线层（R4/审计底线）做省略**

## Phase 3: User Story 1 (P1) — 厚/薄模式

**Goal**: 厚=六层全启；薄=省审批+配额，保留身份/RBAC/脱敏/审计/红线。
**独立测试**: 薄模式省审批/配额；身份/RBAC/脱敏/审计仍生效；默认厚。

- [x] T005 实现 `layer_switch.py`：厚/薄模式的启用层集合解析
- [x] T006 实现默认厚模式（新租户/新场景未配置 → 厚，FR-8）
- [x] T007 US1 测试：厚/薄层集合 + 默认厚

## Phase 4: User Story 2 (P1) — 维度差异化 + 切换时机

**Goal**: 按场景/租户/工具差异化；同 Agent 跨场景不同厚度；工具调用级生效。
**独立测试**: 优先级 场景>租户>工具；每次调用按各自 profile。

- [x] T008 实现 profile 解析入口（每次工具调用解析 会话+租户+工具，返回生效厚度）
- [x] T009 US2 测试：优先级覆盖 + 逐调用生效

## Phase 5: User Story 3 (P2) — 底线守护 + 审计

**Goal**: R4 红线不可降档；审计底线不可关；厚度配置变更留审计。
**独立测试**: R4 任意模式 deny；薄模式审计 ≥ 四元组；配置变更进审计。

- [x] T010 实现审计底线（薄模式最小四元组，FR-6）
- [x] T011 实现 R4 红线守护（任意模式走 001 deny，FR-5）
- [x] T012 实现配置变更审计（FR-7）
- [x] T013 US3 测试：红线不可降 + 审计底线 + 配置审计

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T014 [P] 与 001 门禁链对接（层开关切到 001 gatekeeper，过渡期挂 approval_runtime/audit）
- [x] T015 写 `quickstart.md` + `contracts/harness-config.md`（profile schema + 层开关契约）

---

## Dependencies

```text
Phase 1 (骨架/schema) → Phase 2 (优先级/底线) → US1 → US2 → US3 → Polish
关键: T004 底线守护是硬约束；T005 层集合被 US2 复用
```

## MVP Scope
- **最小 = Phase 1 + Phase 2 + US1**（T001–T007）：厚/薄模式 + 底线守护，即可按模式切换门禁层集合。
- 增量：US2（维度差异化）→ US3（底线审计）。

## Notes
- 019 是 001 六层门禁的"启用哪几层"开关层，不改 001 语义；默认厚，降级需显式配置。
- 与 001/009/006 的跨特性关系已在 spec 双向声明。
- 未改 services 源码；本文件仅在 `specs/019-harness-elastic-config/` 下。
