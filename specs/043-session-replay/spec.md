# Feature Specification: 会话回放（轨迹 tab 可回放化）

**Feature Branch**: `043-session-replay`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案 §4.12：把 028 的"轨迹只读陈列"升级为"可回放"——事件流 + 状态快照的时间轴重演（前端纯投影，零后端改动起步，先做"跳转到某轮查看当时上下文"）。文章口径：「Trace 瀑布里每步输入/输出/耗时/成本/命中知识/调用工具可下钻；会话回放逐步审视」。

> **设计来源**：本规约来自 `docs/MOGO-AgentOS整合方案.md` §4.12（2026-10-23 代码级勘察结论）。
>
> **性质说明**：**全新特性，代码尚未开工**——与 031 的"回溯补规格"本质不同，本特性先把规约拍板再进入实现；`tasks.md` 全部任务未勾选。
>
> **背景事实（代码级核实）**：028 轨迹 tab（`apps/user-web/src/features/execution-v3/components/SessionTrajectoryView.vue`）注释明言 "The conversation and the trajectory are two projections of the SAME V3 event stream … Read-only by design"；Stage 1 按 assistant round 堆叠渲染 `ExecutionViewV3`，**跨轮聚合时间轴是 Stage 2**；数据聚合在 `apps/user-web/src/features/execution-v3/domain/trajectoryRounds.ts`（`collectTrajectoryRounds` 纯函数）；双 tab 机制在 `apps/user-web/src/components/chat/ChatViewTabs.vue` + `App.vue:2656-2720`（`v-show`）+ `useChatRuntimeStore.ts:104-107,746-747`（pane 级 `activeView`）；事件协议在 `domain/protocol.ts`（`V3EventType` / `V3ItemKind`），耗时工具在 `domain/runTiming.ts`；全仓 `replay` 命中均为无关语义（MFA anti-replay、SSO 防重放、`services/chat-api/dsh/runtime-host/src/event-journal.mjs` 的断线重连续传），**无既有回放实现可复用**。

## 定位（一句话）

把 028 的"轨迹只读陈列"升级为"可回放"：**Stage 1 为前端纯投影 MVP**（零后端改动起步）——轨迹 tab 内新增跨轮时间轴、"跳转到某轮查看当时上下文"（事件流内跳转，展开当轮输入/输出/工具调用/知识命中）与步骤详情下钻（输入/输出/耗时，成本按 035 落地情况降权展示）；**Stage 2 真回放**（状态快照序列 + 重演执行）后置，本特性只做技术预研结论记录与接口预留，边界写入 Non-Goals。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 两阶段边界 | **Stage 1 = 前端纯投影 MVP**（user-web 改动，`services/` 零改动）：时间轴 + 跳轮 + 下钻面板；**Stage 2 = 真回放后置**：需状态快照序列 + 重演执行，本特性只做预研结论记录（plan.md）与接口预留（不破坏事件流结构），不放量实现 | plan.md §Summary；Non-Goals |
| 2 | 回放的定位单位 | 一级定位单位 = **assistant round**（延续 028 既有聚合单位 `collectTrajectoryRounds`，轮次 = 一条 assistant 消息）；二级下钻单位 = 单步事件（item）；**不做单步事件级独立回放**（那会脱离"轮"的语境，输入/输出不完整） | `trajectoryRounds.ts` 复用 |
| 3 | 与对话 tab 的共存 | 延续 028 的 `v-show` 双 tab 与 pane 级状态（`useChatRuntimeStore.activeView`）；回放焦点（当前轮 + 展开步骤）为**轨迹 tab 局部 state**，不污染对话 tab、不持久化；`ChatWindow.vue` 零改动 | `App.vue` / `ChatViewTabs.vue` 复用不改 |
| 4 | 成本下钻的依赖 | 单步成本金额依赖 **035（成本归集补维，未落地）**：Stage 1 下钻面板对成本字段**降权展示**——事件里有成本数据才渲染该行，没有则不渲染、**不伪造数值**（与 008 `dashboard.py:713-716` 诚实占位同风）；035 落地后自动生效，无需再改面板 | 下钻面板组件 |
| 5 | Stage 2 的触发条件 | 仅当同时满足：① 出现"必须复现当时完整状态"的硬场景（审计举证 / 缺陷复现 / 同输入对比重演）；② Stage 1 的使用数据证明跳转/下钻频率高、投影式不够用——才立项真回放；否则维持投影式回放（投影 = 对已记录事件的确定性重放，不含环境副作用） | plan.md 预研结论 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 跨轮时间轴与"跳转到某轮查看当时上下文" (Priority: P1)

用户在轨迹 tab 顶部看到一条跨轮时间轴（每个 assistant round 一个锚点，标注轮次与时间）；点击任一锚点，视图立即定位到该轮并展开当轮完整上下文——该轮的输入（用户消息/上下文引用）、输出（final_answer）、工具调用、知识命中，逐项可读，如同"回放"到那一刻。

**Why this priority**: 这是文章"会话回放逐步审视"的核心动作，也是 Stage 1 的全部价值所在——没有时间轴与跳转，"回放"就只是 028 的静态陈列；有了它，审查者可以逐轮审视当时 Agent 到底看到了什么、做了什么。

**Independent Test**: 打开一个 ≥3 轮且有工具调用的历史会话，在轨迹 tab 点击第 2 轮锚点，视图定位到第 2 轮且展开当轮全部步骤（含工具调用与知识命中项）；再点第 1 轮，焦点正确切换、第 2 轮可折叠收回。

**Acceptance Scenarios**:

1. **Given** 一个有多轮历史的会话，**When** 用户打开轨迹 tab，**Then** 顶部呈现跨轮时间轴，每轮一个锚点（轮次号 + 时间），锚点数量 = assistant 轮数，不渲染非 assistant 消息。
2. **Given** 时间轴已呈现，**When** 用户点击第 N 轮锚点，**Then** 视图定位到第 N 轮并展开当轮完整上下文（输入 / 输出 / 工具调用 / 知识命中）。
3. **Given** 当前聚焦第 N 轮，**When** 用户点击另一轮锚点，**Then** 焦点切换到该轮，前一轮恢复为折叠摘要态（不丢失其数据）。
4. **Given** 一个新会话（无任何 assistant 轮次），**When** 打开轨迹 tab，**Then** 时间轴不渲染、显示既有空态提示（`chat.view.trajectory_empty`），不报错。

---

### User Story 2 - 步骤详情下钻（输入/输出/耗时/成本降权） (Priority: P1)

在某轮上下文内，用户点击任一步骤（item：思考/工具调用/知识命中/产物等），弹出/展开下钻面板，显示该步的输入、输出与耗时；若事件流中带有单步成本数据（依赖 035），面板附加成本行，否则不显示该行。

**Why this priority**: 文章"Trace 瀑布里每步输入/输出/耗时/成本/命中知识/调用工具可下钻"的直接落地；下钻是"逐步审视"的二级动作，与 US1 的跳转共同构成完整回放体验。

**Independent Test**: 在一轮含工具调用的会话中，点击工具调用步骤，下钻面板显示工具名、输入参数摘要、输出摘要与耗时（`runTiming` 格式化）；在一轮无成本数据的老会话中执行同样操作，面板不出现成本行且不报错。

**Acceptance Scenarios**:

1. **Given** 某轮已展开，**When** 用户点击任一步骤，**Then** 下钻面板显示该步输入、输出与耗时（耗时按 `runTiming.ts` 既有格式化，运行中实时滚动）。
2. **Given** 步骤为工具调用，**When** 查看下钻面板，**Then** 显示工具名与参数/结果摘要（沿用 `ExecutionViewV3` 既有展示口径，不新造渲染）。
3. **Given** 步骤为知识命中，**When** 查看下钻面板，**Then** 显示命中来源（知识条目/引用），口径与对话 tab 的引用展示一致。
4. **Given** 事件流中无单步成本数据（035 未落地），**When** 查看下钻面板，**Then** 不渲染成本行、不显示占位假值；035 落地后同一面板自动显示成本行。

---

### User Story 3 - 运行中实时跟随 + 028 零回归 (Priority: P2)

会话正在生成时，轨迹 tab 的处理过程实时增长（时间轴锚点动态追加），用户的跳转/下钻操作不中断流式生成；切回对话 tab，问答气泡与切换前完全一致——028 的全部既有行为（tab 切换、pane 独立、空态、流不中断）零回归。

**Why this priority**: 这是"不回退"的守护型故事——本特性所有增强都挂在 028 的既存机制上，必须证明叠加后原有体验无损；实时跟随同时保证回放视图对"进行中的会话"同样可用。

**Independent Test**: 发送一条消息，生成过程中切到轨迹 tab，可见锚点与步骤逐条出现；期间点击任意锚点与步骤下钻；切回对话 tab，正文仍在流式输出且 ChatWindow 无 diff（`git diff` 断言）；`pnpm test` 与 `vue-tsc` + `vite build` 全绿。

**Acceptance Scenarios**:

1. **Given** 会话正在生成，**When** 用户处于轨迹 tab，**Then** 新产生的轮次/步骤实时出现（时间轴锚点动态追加），无需刷新。
2. **Given** 用户正在轨迹 tab 跳转/下钻，**When** 生成继续进行，**Then** 流不中断、事件不丢失（视图操作不得触发 ChatWindow 卸载或流中断）。
3. **Given** 改造完成，**When** 对比 028 交付态，**Then** 对话 tab 行为逐项一致（`ChatWindow.vue` 零 diff、tab 切换无网络请求、pane 状态独立、刷新回默认 tab）。
4. **Given** 多 pane 场景，**When** 两个会话分别停在轨迹/对话 tab 且各自有回放焦点，**Then** 互不串味。

---

### Edge Cases

- **老会话无 `execution_events`**：轨迹 tab 显示既有空态，时间轴不渲染，不抛错（延续 028 Edge Case）。
- **超长会话（数百轮）**：时间轴按轮次锚点轻量渲染（DOM 数量 = 轮次数，不展开全部步骤），点击锚点才加载/展开该轮详情；锚点过多时提供"跳到最新/最旧"快捷位。
- **事件缺 `item_id` / `parent_item_id`**：下钻面板降级为只读摘要（显示可解析字段），不猜测层级。
- **聚焦轮正在进行中**：该轮锚点带运行中指示（`store.state.runStatus === 'running'`，028 既有 `live` 口径），耗时实时滚动。
- **会话在跳转后产生新轮次**：时间轴自动追加新锚点，焦点不强制跳走（用户可继续审视原轮）。
- **多 pane 并发生成**：各 pane 的轨迹视图与焦点独立（焦点为组件局部态，不入 store）。
- **浏览器刷新**：焦点回默认（pane 内存态，延续 028 不持久化决策）。
- **轮次内步骤极多（长任务）**：步骤列表虚拟滚动或分组折叠（`repeatedToolCalls` 既有分组口径可复用），避免一次渲染数千节点。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 轨迹 tab MUST 提供跨轮时间轴：每个 assistant round 一个锚点，含轮次号与时间，锚点数量 = 轮数，不渲染非 assistant 消息。
- **FR-002**: 用户 MUST 能通过时间轴跳转到任意轮次，并查看该轮完整上下文：输入（用户消息/上下文引用）、输出（`final_answer`）、工具调用、知识命中。
- **FR-003**: 用户 MUST 能对任一步骤（item）下钻，查看其输入、输出与耗时；耗时格式化与运行中实时滚动 MUST 复用 `domain/runTiming.ts` 既有口径。
- **FR-004**: 下钻面板的成本行 MUST 降权展示：事件流含成本数据才渲染，否则不渲染且 MUST NOT 伪造数值（035 未落地时的既定行为）。
- **FR-005**: 轨迹 tab MUST 在会话生成过程中实时更新（新轮次/步骤即时出现），且用户的跳转/下钻操作 MUST NOT 中断流式生成（延续 028 FR-006/FR-007）。
- **FR-006**: 对话 tab MUST 零回归：`ChatWindow.vue` 零改动，028 的全部验收（tab 切换、pane 独立、空态、无网络请求）继续成立。
- **FR-007**: Stage 1 实现 MUST 为纯前端：`services/` 目录零改动（零后端接口、零新查询）。
- **FR-008**: 双 tab 共存 MUST 延续 028 机制：`v-show` 切换（`App.vue:2656-2720`）+ pane 级 `activeView`（`useChatRuntimeStore.ts:104-107`）。
- **FR-009**: 回放焦点状态（当前轮 + 展开步骤集合）MUST 为轨迹 tab 组件局部态：不写入 store、不持久化、不污染对话 tab。
- **FR-010**: Stage 2（真回放）MUST 仅以预研结论 + 接口预留形式存在：不得为实现 Stage 2 而破坏性变更 V3 事件流结构（`domain/protocol.ts`）；任何 Stage 2 立项须走新 spec。

### Key Entities

- **TrajectoryRound**（既有，028）：`{key, index, message}`，`collectTrajectoryRounds` 产出；本特性中作为时间轴锚点与一级定位单位。
- **ReplayFocus**（新增，前端局部态）：`{roundKey: string | null, expandedStepIds: Set<string>}`，轨迹 tab 组件内 state，不持久化。
- **StepDrilldown**（新增，视图模型）：`{stepId, kind, input, output, durationMs, cost?}`——`cost` 仅在事件流提供时存在。
- **SessionCommit**（002 既有，关系声明）：002 的 `session_snapshots` 快照是 Stage 2 真回放的天然定位锚（"回放到某个 commit 版本"）；Stage 1 不消费快照。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 任一会话可在轨迹 tab 内跳转到任意轮次并看到当轮完整上下文（输入/输出/工具调用/知识命中），跳转响应为纯前端计算、无网络请求。
- **SC-002**: 每个步骤可下钻看到输入/输出/耗时；成本行仅在数据存在时出现（老会话零成本行）。
- **SC-003**: 028 既有对话 tab 零回归：`ChatWindow.vue` 零 diff，`pnpm test` 全绿。
- **SC-004**: `vue-tsc` + `vite build`（user-web）通过。
- **SC-005**: Stage 1 全前端改动：`git diff --stat services/` 为空；Stage 2 预研结论记录在 plan.md，接口预留不破坏事件流结构（`domain/protocol.ts` 零 diff）。

## Assumptions

- 轨迹数据 = 同一批 V3 事件的投影（028 前提不变）：回放不引入新数据源、不重放环境副作用，"回放"指对已记录事件的确定性重放。
- 单步成本依赖 035（成本归集补维）透出；035 未落地前成本行隐藏，落地后自动显示。
- 002 的 commit 版本定位为关系声明：Stage 1 只读当前消息列表，不做版本切换 UI。
- 023（可观测性）为后端 Trace 数据源：Stage 1 只用消息内 `execution_events`（前端已有投影），不直连后端 Trace 接口。
- 耗时数据来源为事件时间戳（`ts` + `runTiming.ts` 既有算法），不新增埋点。

## 跨特性关系（被依赖方视角，双向声明）

- **与 028（user-web-trajectory-tab）**：本特性是 028 的**直接扩展**——复用其组件（`SessionTrajectoryView.vue`）、聚合（`domain/trajectoryRounds.ts`）、双 tab 机制（`ChatViewTabs.vue` + `useChatRuntimeStore.activeView`）与"只读、纯前端、对话零回归"边界；028 的 FR-001~FR-009 全部延续，028 spec 的行为描述继续成立（本特性只做增强不做改写）。
- **与 002（session-versioning）**：002 的 commit 快照（`session_snapshots`，002 FR-12）是 Stage 2 真回放的天然定位锚（"回放到某个 commit 版本"的上下文边界）；Stage 1 不消费快照，仅为关系声明；002 的线性时间线（resume 永不分叉）为"按轮定位"提供了确定性前提。
- **与 023（observability-resilience）**：后端全链路 Trace 属 023；本特性 Stage 1 只用消息内 `execution_events`（前端投影），不新增后端查询；若 Stage 2 立项，快照数据源将与 023 的 Trace 存储对齐（预留声明）。
- **与 035（成本归集补维，未来 spec）**：单步成本金额依赖 035 透出到事件流；未落地前降权隐藏（FR-004）；两特性无强耦合，035 落地即自动增强本面板。

## Non-Goals

- 不做 Stage 2 真回放（状态快照序列 + 重演执行）——仅预研结论与接口预留；真回放须另立 spec。
- Stage 1 不改后端：`services/` 目录零改动。
- 不改 `ChatWindow.vue` 与对话 tab 的任何行为。
- 不做跨会话对比回放、回放结果分享/导出。
- 不做审批交互（延续 028：审批留在对话 tab，轨迹 tab 只读）。
- 不持久化回放焦点（pane/组件内存态，刷新回默认）。
- 不做单步事件级独立回放（定位单位是轮，不是步）。
