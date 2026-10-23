# Implementation Plan: 会话回放（轨迹 tab 可回放化）（043-session-replay）

**Branch**: `043-session-replay` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/043-session-replay/spec.md`

**Note**: **全新特性**（整合方案 §4.12 立项，代码尚未开工）——spec 先行，tasks 全部未勾选。Stage 1 为纯前端 MVP，Stage 2 仅预研。

## Summary

把 028 的会话级「轨迹」tab 从"只读陈列"升级为"可回放"。**Stage 1（本特性 MVP，纯前端、零后端改动）**：在既有 `SessionTrajectoryView.vue` 基础上新增 ① 跨轮时间轴（每 assistant round 一个锚点，复用 `collectTrajectoryRounds`）② 跳转到任意轮次并展开当轮完整上下文（输入/输出/工具调用/知识命中）③ 步骤详情下钻面板（输入/输出/耗时，成本字段按 035 落地情况降权展示）。焦点态为组件局部 state，延续 028 的 `v-show` 双 tab 与 pane 级 `activeView`，`ChatWindow.vue` 零改动。**Stage 2（真回放：状态快照序列 + 重演执行）**：仅产出技术预研结论（见下）与接口预留（不破坏 V3 事件流结构），不放量实现。

**Stage 2 预研结论（记录于此，作为触发条件的判据）**：

1. **数据充分性**：V3 事件流（`domain/protocol.ts`）已含每步输入/输出/时间戳，投影式"回放"（Stage 1）对**审视**类需求已充分；真回放的增量价值仅在"重演执行并对比"（同输入不同结果）与"复现当时完整环境状态"（审计举证）。
2. **环境依赖**：重演执行需要还原当时的模型版本/工具可用性/知识库状态——这些运行时状态当前**未随事件流持久化**（002 的 `session_snapshots` 快照含上下文摘要但非执行环境全量）；补齐它等于新建一套执行环境快照体系，成本远超 Stage 1。
3. **结论**：Stage 2 的首个值得立项的场景最可能是"审计举证"（配合 022 审计链），触发条件以 spec 已定决策 #5 为准（硬场景出现 + Stage 1 使用数据证明投影式不够）；在触发前，接口预留仅为"事件流结构不做破坏性变更 + 快照定位锚挂 002 commit"两条纪律，不写任何预留代码。

## Technical Context

**Language/Version**: TypeScript 5（user-web，Vue 3 + `<script setup>` SFC）

**Primary Dependencies**: Vue 3 响应式（`computed`/`ref`）、既有 `@/features/execution-v3/*`（组件 + domain + stores）、`@/composables/i18n`（`t()`）、`@/composables/appTimezone`（`formatAppTime`）；**不引入新依赖**（时间轴/下钻为自绘轻量组件，不引第三方时间线库）

**Storage**: N/A——纯前端投影，数据源为会话消息内 `execution_events`（028 前提：对话与轨迹是同一批 V3 事件的两种投影）；焦点态为组件内存态，不写 localStorage、不落服务端

**Testing**: user-web `pnpm test`（vitest，既有测试树全绿 = 028 零回归）；`domain/trajectoryRounds.ts` 的纯函数单测扩展（锚点派生）；`vue-tsc` + `vite build` 全量通过

**Target Platform**: 浏览器（user-web，Vite 构建产物经 nginx 服务）

**Project Type**: web-app（user-web 前端）

**Performance Goals**: 时间轴锚点渲染 DOM 数 = 轮数（不展开步骤）；点击锚点才展开该轮；长会话（数百轮）锚点列表保持轻量（必要时"跳到最新/最旧"快捷位）；跳转为纯前端滚动/聚焦，无网络请求、主观无延迟

**Constraints**: `services/` 零改动；`ChatWindow.vue` 零改动；`domain/protocol.ts`（事件流结构）零 diff（Stage 2 预留纪律）；延续 028 的只读边界（轨迹 tab 不处理审批）；新文案走 `t()` 中文 key 回退保持中英双语

**Scale/Scope**: 1 个既有组件增强（`SessionTrajectoryView.vue`）+ 1-2 个新局部组件（时间轴、下钻面板）+ 1 个 domain 纯函数扩展；0 新依赖、0 后端改动

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本三件套先于代码；两阶段边界、定位单位、共存机制、成本降权、Stage 2 触发条件五个决策点已拍板。
- **II. Enterprise Production Readiness**: ✅ 纯前端投影无新增失败面；老会话/缺字段/超长会话均有降级路径（空态、只读摘要、锚点轻量渲染）；零回归由 `pnpm test` + `git diff` 断言守护。
- **III. Security and Data Protection**: ✅ 无新增数据出口：回放只读既有消息内事件（已过 001 脱敏与租户隔离的同一份数据），不新增接口、不新增存储；轨迹 tab 延续只读（无审批/权限操作面）。
- **IV. Cross-Platform and i18n**: ✅ 新文案（时间轴/跳转/下钻标签）走 `t()` 中文 key 回退，`locales/messages.ts` 既有模式（028 的 `chat.view.trajectory*` 键即此模式）。
- **V. Observability and Simplicity**: ✅ 复用 028 既有组件/聚合/store 三层结构，新增仅为"时间轴 + 焦点态 + 下钻面板"三个小件；不引入状态管理库、不引第三方时间线组件；Stage 2 明确后置，YAGNI。

## Project Structure

### Documentation (this feature)

```text
specs/043-session-replay/
├── spec.md              # 特性规约（两阶段边界/FR/SC/关联特性）
├── plan.md              # 本文件（含 Stage 2 预研结论）
└── tasks.md             # 任务清单（Phase 0-3，全部未勾选）
```

### Source Code (repository root)

```text
apps/user-web/
└── src/features/execution-v3/
    ├── components/
    │   ├── SessionTrajectoryView.vue      # 【修改】挂载时间轴；焦点态（当前轮/展开步骤）；
    │   │                                   #  轮次区按焦点折叠/展开；运行中指示延续 live 口径
    │   ├── TrajectoryTimeline.vue         # 【新增】跨轮时间轴（锚点 = 轮次 + 时间；
    │   │                                   #  跳转到最新/最旧快捷位；纯展示 + emit 焦点事件）
    │   └── StepDrilldownPanel.vue         # 【新增】步骤下钻面板（输入/输出/耗时；
    │                                       #  成本行按数据存在性条件渲染——035 降权）
    └── domain/
        ├── trajectoryRounds.ts            # 【修改】扩展：时间轴锚点派生（轮次 + 时间 + live），
        │                                   #  保持纯函数可单测（既有 collectTrajectoryRounds 不改签名）
        └── runTiming.ts                   # 【复用不改】耗时计算与格式化

# 【复用不改】apps/user-web/src/components/chat/ChatViewTabs.vue（双 tab 组件）
# 【复用不改】apps/user-web/src/App.vue:2656-2720（v-show 双视图挂载）
# 【复用不改】apps/user-web/src/composables/useChatRuntimeStore.ts（pane 级 activeView）
# 【复用不改】apps/user-web/src/components/ChatWindow.vue（对话 tab，零 diff）
# 【复用不改】apps/user-web/src/features/execution-v3/components/ExecutionViewV3.vue（轮次内渲染）
# 【复用不改】apps/user-web/src/features/execution-v3/domain/protocol.ts（V3 事件流结构，Stage 2 预留纪律）
# 【复用不改】apps/user-web/src/features/execution-v3/stores/executionStore.ts / messageExecution.ts
# 【零改动】services/（Stage 1 纯前端）
```

**Structure Decision**: 完全贴合 028 的分层（组件 / domain 纯函数 / stores）——新增逻辑优先落 `domain/` 纯函数（可单测、无 Vue 依赖），组件只做挂载与焦点编排；不新增 store（焦点态刻意保持局部，避免多 pane 串味并延续 028"不持久化"决策）；时间轴与下钻面板为两个自绘小组件，不引第三方时间线库（依赖最小化）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**（记录备查）：① 焦点态入 store（跨组件共享）——焦点只服务于轨迹 tab 单视图，入 store 会引入多 pane 串味与持久化诱惑，违背 028 决策；② 虚拟滚动库——数百轮锚点为轻量 DOM，先用"不展开 + 快捷跳转"兜底，真到性能问题再评估；③ Stage 2 预留代码（快照接口/适配层）——无触发场景的预留即负债，只保留"事件流结构不破坏"的纪律约束。
