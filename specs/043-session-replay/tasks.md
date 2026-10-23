# Tasks: 会话回放（轨迹 tab 可回放化）（043-session-replay）

**Input**: Design documents from `/specs/043-session-replay/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性**（整合方案 §4.12 立项，代码尚未开工）——spec 先行，tasks 全部未勾选；Stage 1 纯前端 MVP，Stage 2 仅预研。

**Tests**: user-web `pnpm test`（vitest，028 零回归）；`domain/trajectoryRounds.ts` 纯函数单测扩展；`vue-tsc` + `vite build` 全量通过。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号，全部 `- [ ]`。

---

## Phase 0: 研究与澄清

- [ ] T001 建立 spec/plan/tasks 三件套（`specs/043-session-replay/`，本文件）
- [ ] T002 盘点 028 交付态的既有结构与口径：`SessionTrajectoryView.vue`（round 堆叠 + live）、`trajectoryRounds.ts`（轮次聚合）、`App.vue` v-show 双视图、`useChatRuntimeStore.activeView`，确认本特性的复用点与禁改点（ChatWindow / protocol.ts）
- [ ] T003 盘点消息内 `execution_events` 的实际字段覆盖率（`item_kind` / `ts` / `payload` 在各步类型的出现率），确认下钻面板"输入/输出/耗时"三字段的数据可得性与缺字段降级路径
- [ ] T004 澄清成本字段现状：确认 035 未落地前事件流中是否完全无单步成本数据（决定 FR-004 降权展示的具体判据——字段缺失 vs 值为空）
- [ ] T005 Stage 2 预研（结论写入 plan.md）：评估"状态快照序列 + 重演执行"的数据缺口（执行环境状态未持久化）、与 002 `session_snapshots` 的定位锚关系、与 023 Trace 存储的对齐可能；明确触发条件与"仅纪律预留、不写预留代码"的边界

## Phase 1: 设计

- [ ] T006 设计时间轴锚点派生纯函数（`domain/trajectoryRounds.ts` 扩展）：输入消息列表 → `{key, index, time, live}[]`，保持既有 `collectTrajectoryRounds` 签名与行为不改（新函数并列）
- [ ] T007 设计焦点态模型（`ReplayFocus`）：`{roundKey, expandedStepIds}` 的组件局部 state 形状、与轮次折叠/展开的映射、多 pane 隔离论证（局部态不入 store）
- [ ] T008 设计 `StepDrilldown` 视图模型与降级规则：`{stepId, kind, input, output, durationMs, cost?}` 各字段从 V3 事件的抽取口径；`cost` 条件渲染判据（T004 结论）；缺 `item_id` 时的只读摘要降级
- [ ] T009 设计长会话性能兜底：锚点轻量渲染 + "跳到最新/最旧"快捷位；步骤极多时的分组/折叠口径（评估复用 `domain/repeatedToolCalls.ts` 既有分组）
- [ ] T010 Constitution Check 复核（plan.md 门禁）：确认零后端改动、ChatWindow 零 diff、protocol.ts 零 diff、无新依赖

## Phase 2: 实现

- [ ] T011 [P] `domain/trajectoryRounds.ts`：实现时间轴锚点派生纯函数（T006），附单测（含无 id 消息的稳定 key、非 assistant 跳过）
- [ ] T012 [P] `components/TrajectoryTimeline.vue`（新增）：锚点列表（轮次 + 时间 + 运行中指示）、跳转 emit、快捷跳转位；纯展示组件，不直接改 store
- [ ] T013 [P] `components/StepDrilldownPanel.vue`（新增）：输入/输出/耗时渲染（`runTiming.ts` 格式化 + 运行中滚动）；成本行按 T004 判据条件渲染；缺字段只读摘要降级
- [ ] T014 `components/SessionTrajectoryView.vue`：挂载时间轴；接入焦点态（T007）驱动轮次折叠/展开；保留既有空态与逐轮堆叠结构；i18n 新文案键（`chat.view.replay_*`）走 `t()` 中文 key 回退
- [ ] T015 接线复查：确认 `App.vue` 双 tab 挂载、`ChatViewTabs.vue`、`useChatRuntimeStore` 零改动即可满足全部 FR（如需微调，限定为纯挂载层且不改对话 tab 行为）

## Phase 3: 验证与接线

- [ ] T016 [P] 单测：锚点派生纯函数（轮数/顺序/稳定 key/live 标记）；下钻面板字段抽取与 `cost` 条件渲染判据
- [ ] T017 [P] 回归：`pnpm test` 全绿（028 既有测试零失败）；`git diff --stat apps/user-web/src/components/ChatWindow.vue` 为空
- [ ] T018 构建：`vue-tsc` + `vite build`（user-web）通过；重点核查新组件无类型回归
- [ ] T019 手工验收：≥3 轮历史会话跳转/下钻全路径；生成中实时跟随不中断；多 pane 焦点隔离；老会话（无 events）空态；`git diff --stat services/` 为空
- [ ] T020 Stage 2 边界核验：`git diff --stat apps/user-web/src/features/execution-v3/domain/protocol.ts` 为空（预留纪律成立）；plan.md 预研结论与触发条件评审通过
- [ ] T021 文档接线：在 028/002 对应 spec 的"跨特性关系"补记本特性的双向声明（仅文档，不改代码）；本目录 tasks 勾选状态更新（含本条）

---

## Dependencies & Execution Order

- Phase 0（T001-T005）全部完成后进入 Phase 1；T004 的结论是 T008 成本判据的输入，T005 预研独立可并行。
- Phase 1：T006-T008 为核心契约，T009 为性能兜底（可与 T006-T008 并行设计）；T010 门禁在 Phase 2 前必须通过。
- Phase 2：T011-T013 三个 [P] 可并行（互不依赖）；T014 依赖三者定稿；T015 为挂载层复查。
- Phase 3：T016-T018 可并行；T019/T020 为放行门禁；T021 收尾。
- Checkpoint：Phase 1 完 = 锚点/焦点/下钻三契约冻结；Phase 2 完 = 时间轴 + 跳转 + 下钻齐备且 028 结构未动；Phase 3 完 = 回归零失败 + 双构建通过 + services/protocol.ts 双零 diff。

## Notes

- 焦点态刻意不入 store：本特性唯一的"状态"只服务轨迹 tab 单视图，入 store 会带来多 pane 串味与持久化诱惑，直接违背 028"tab 状态 pane 级、刷新回默认"的决策精神。
- `collectTrajectoryRounds` 是 028 的公共纯函数（被 `SessionTrajectoryView.vue` 消费），本特性以**新函数并列**方式扩展（不改其签名），保证 028 行为零漂移。
- 成本行判据以 T004 澄清结论为准：字段缺失与值为空是两种判据，取"事件中不存在成本字段即不渲染"，避免把 0 值误渲染成"免费"。
- Stage 2 的接口预留只有两条纪律：① `domain/protocol.ts` 零 diff；② 定位锚概念挂 002 commit（文档级）。不写任何预留代码/适配层——无触发场景的预留即负债。
