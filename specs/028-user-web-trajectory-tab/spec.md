# Feature Specification: user-web 会话级「对话 / 轨迹」双 tab（路线 C）

**Feature Branch**: `028-user-web-trajectory-tab`

**Created**: 2026-10-15

**Status**: Draft

**Input**: 用户要求按 `docs/user-web-复用dsh-web会话能力-方案.md` 的**路线 C** 落地——在 user-web 会话页把 execution-v3 从「每条 assistant 消息内联」提升为**会话级「轨迹」tab**，与「对话」tab 并列切换。

## 背景与边界

**现状**：user-web 顶层视图枚举无 `trajectory`（`apps/user-web/src/App.vue:120`）；「轨迹」目前是每条 assistant 消息内联的可折叠处理过程（`apps/user-web/src/components/ChatWindow.vue:2005-2009` + `apps/user-web/src/features/execution-v3/`）。

**目标形态**：会话级两个可切换 tab（对话 / 轨迹），对齐官方 dsh web 由 `dsh-client-ui-conversation` view-selection 提供的 `chat` / `trajectory` 双视图体验。

**明确不做**（路线 C 的边界，理由见方案文档 §3 硬约束 C1–C7）：

- 不嵌入官方 dsh web GUI（iframe）
- 不直连官方 `/api`（Typert Remote / WebSocket mux）
- 不引入 `@deepseek-ai/dsh-client-ui-*`（前端架构不兼容：React + cordis vs Vue 3）
- 不绕过 chat-api 业务治理（多租户 / 配额 / 企业技能准入 / 审批 / Mongo 持久化）

**关键前提**：user-web 的「对话」与「轨迹」**同源**——都是同一批 V3 事件的两种投影（对话 = `final_answer` 文本，轨迹 = 全部 `item.*` 过程项，见 `services/chat-api/app/dsh_runtime/events/projection.py`）。因此本特性在**数据层零新增**，纯前端视图层改动。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 会话级「对话 / 轨迹」tab 切换 (Priority: P1)

用户在会话页顶部看到「对话」「轨迹」两个 tab，点击即可切换当前会话的呈现方式：对话 tab 显示熟悉的问答气泡，轨迹 tab 显示本次会话全部轮次的处理过程（工具调用、思考、产物等）。

**Why this priority**：这是本特性的核心价值——把散落在每条消息里的处理过程，提升为可整体浏览的会话级视图，对齐官方 dsh web 的体验。

**Independent Test**：打开任一有历史的会话，点击「轨迹」tab，能看到跨轮次的处理过程列表；点回「对话」，问答气泡与切换前完全一致。

**Acceptance Scenarios**：

1. **Given** 一个已有多轮对话的会话，**When** 用户点击「轨迹」tab，**Then** 页面展示该会话全部 assistant 轮次的处理过程（按时间顺序），且不显示问答正文气泡。
2. **Given** 用户处于「轨迹」tab，**When** 点击「对话」tab，**Then** 恢复原有问答气泡视图，滚动位置与内容与切换前一致。
3. **Given** 一个新会话（无任何消息），**When** 用户查看两个 tab，**Then** 轨迹 tab 显示空态提示，不报错。

---

### User Story 2 - tab 偏好按会话独立保持 (Priority: P2)

用户在多会话之间切换时，每个会话各自记住自己停留在哪个 tab。

**Why this priority**：多 pane 是 user-web 的既有能力（`useChatRuntimeStore` 最多缓存 8 个 pane）。若 tab 状态全局共享，切换会话会串味。

**Independent Test**：会话 A 切到「轨迹」，切到会话 B（应为「对话」），再切回 A，A 仍停留在「轨迹」。

**Acceptance Scenarios**：

1. **Given** 会话 A 停在「轨迹」tab，**When** 用户切到会话 B 再切回 A，**Then** A 仍停在「轨迹」。
2. **Given** 新建一个会话，**When** 首次进入，**Then** 默认停在「对话」tab。

---

### User Story 3 - 运行中实时跟随 (Priority: P3)

会话正在生成时，切到「轨迹」tab 能看到处理过程实时增长；切回「对话」后正文继续流式更新。

**Why this priority**：轨迹与对话消费同一份 execution store，天然实时；但需确保切换视图不打断流。

**Independent Test**：发送一条消息，生成过程中切到「轨迹」，可见工具调用逐条出现；切回「对话」，正文仍在流式输出。

**Acceptance Scenarios**：

1. **Given** 会话正在生成，**When** 用户切到「轨迹」tab，**Then** 新产生的处理项实时出现，无需刷新。
2. **Given** 会话正在生成且用户停在「轨迹」tab，**When** 生成完成，**Then** 轨迹 tab 反映终态（不再有运行中指示）。

### Edge Cases

- **无轨迹数据**：历史消息的 `execution_events` 为空（老会话）→ 轨迹 tab 显示空态，不抛错。
- **切换时机**：在流式输出中切换 tab → 不得中断 `useChatStream` 的读取或丢失事件（视图切换不得触发 ChatWindow 卸载重建导致的流中断）。
- **多 pane 并发**：多个会话同时运行时，各自 tab 状态独立，互不影响。
- **浏览器刷新**：刷新后回到会话，tab 状态（本特性为 pane 内存态）回到默认「对话」——可接受，不要求持久化到服务端。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 会话页 MUST 提供「对话」与「轨迹」两个可切换 tab。
- **FR-002**: 默认 tab MUST 为「对话」。
- **FR-003**: 「轨迹」tab MUST 聚合展示**当前会话全部 assistant 轮次**的处理过程（跨轮次、按时间顺序），而非仅最后一轮。
- **FR-004**: tab 状态 MUST 按会话（pane）独立保存，切换会话不串味。
- **FR-005**: 「对话」tab MUST 完整保留现有 ChatWindow 行为（消息气泡、产物、审批、滚动、吸顶等），**零回归**。
- **FR-006**: 「轨迹」tab MUST 在会话生成过程中实时更新。
- **FR-007**: 视图切换 MUST NOT 中断正在进行的流式生成。
- **FR-008**: 文案 MUST 支持中英双语（`zh` / `en`）。
- **FR-009**: 实现 MUST NOT 引入官方 dsh 前端依赖，也 MUST NOT 绕过 chat-api（架构边界）。

### Key Entities

- **ChatRuntimePane**：会话 pane 状态容器（`apps/user-web/src/composables/useChatRuntimeStore.ts:85-103`）。本特性为其新增「当前视图」维度。
- **ExecutionStoreV3**：单条 assistant 消息的轨迹状态机（`apps/user-web/src/features/execution-v3/stores/executionStore.ts`），按消息附着（`messageExecution.ts:38-69` 的 `ensureMessageExecutionV3`，幂等）。
- **视图 tab**：`chat` | `trajectory` 两个枚举值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 切换 tab 为纯前端状态切换，无网络请求，主观无延迟。
- **SC-002**: user-web 现有测试全绿（`pnpm test`），零回归。
- **SC-003**: 「对话」tab 的渲染结果与改造前一致（ChatWindow 文件零改动）。
- **SC-004**: 轨迹 tab 能正确呈现 ≥2 轮历史的会话的全部轮次处理过程。

## Assumptions

- **第一版范围**：轨迹 tab 复用现有 `ExecutionViewV3` 组件**逐消息纵向渲染**（阶段 1 最小可用），不做跨轮次聚合时间线/表格（那是方案文档的阶段 2，后续单独迭代）。
- **审批交互**：轨迹 tab 内**不**处理审批/权限交互（`resolve-permission`），审批仍在对话 tab 完成；轨迹 tab 为只读展示。理由：现有 `resolvePermission → POST /chat/permission` 是死链路（后端无此路由），不应在新视图里复制这条路径。
- **不持久化**：tab 偏好为 pane 内存态，不写 localStorage、不同步服务端。
- **不改后端**：本特性纯前端，`services/` 下零改动。
- **不影响池化/部署**：不涉及 compose、nginx、镜像。

## 跨特性关系（后续补记）

- **043-session-replay（会话回放，2026-10-24）**：在本特性的轨迹 tab 之上叠加 Stage 1 回放能力——跨轮时间轴（`collectTrajectoryAnchors` 复用本特性 `collectTrajectoryRounds`，不改其签名与行为）、单轮聚焦、步骤下钻（输入/输出/耗时，成本行按数据存在性条件渲染）。
  - 本特性的 `SessionTrajectoryView.vue` 由 043 扩展（新增时间轴与焦点折叠），**默认无焦点时渲染行为与本特性完全一致**（逐轮堆叠全展开）。
  - 本特性 SC-003「ChatWindow 零改动」在 043 中继续成立；`domain/protocol.ts` 同样零 diff。
  - 本特性 Assumptions 中"跨轮次聚合时间线是阶段 2、后续单独迭代"由 043 承接并落地为 Stage 1（轻量时间轴），非重演执行。

