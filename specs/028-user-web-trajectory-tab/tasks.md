# Tasks: user-web 会话级「对话 / 轨迹」双 tab（路线 C）

**Input**: Design documents from `specs/028-user-web-trajectory-tab/`
**Prerequisites**: plan.md, spec.md

## Phase 1: 状态层

- [ ] T001 [US1] 在 `apps/user-web/src/composables/useChatRuntimeStore.ts` 的 `ChatRuntimePane` 类型新增 `activeView: 'chat' | 'trajectory'`；`createPane()` 初始化 `activeView: 'chat'`；新增 `setPaneView(key: string, view: 'chat' | 'trajectory')` 并在 `return` 中导出（`useChatRuntimeStore.ts:784-803`）

## Phase 2: 组件层

- [ ] T002 [P] [US1] 新建 `apps/user-web/src/components/chat/ChatViewTabs.vue`：props `view`，emit `update:view`；两个 tab 按钮 + 选中态；文案 `t('chat.view.chat')` / `t('chat.view.trajectory')`
- [ ] T003 [P] [US1] 新建 `apps/user-web/src/features/execution-v3/components/SessionTrajectoryView.vue`：props `messages`；过滤 assistant 消息，逐条 `ensureMessageExecutionV3(msg)` 渲染 `ExecutionViewV3`（纵向堆叠，标注轮次）；空态兜底；不绑定 `resolve-permission`
- [ ] T004 [P] [US1] 在 `apps/user-web/src/locales/messages.ts` 新增 `'chat.view.chat'` 与 `'chat.view.trajectory'`（zh/en）

## Phase 3: 接线

- [ ] T005 [US1] 修改 `apps/user-web/src/App.vue:2557-2562`：pane 容器改 `flex h-full w-full flex-col`；顶部挂 `<ChatViewTabs>`；内容区 `relative min-h-0 flex-1` 内用 `v-show` 切换 `ChatWindow` / `SessionTrajectoryView`；引入两个新组件
- [ ] T006 [US3] 确认用 `v-show`（非 `v-if`）保持 ChatWindow 挂载，避免切换中断流式生成（FR-007）

## Phase 4: 测试与验证

- [ ] T007 [P] 新建 `apps/user-web/tests/trajectory-view-tabs.test.ts`：覆盖 ① 默认视图为 chat；② `setPaneView` 按 pane 独立；③ 轨迹视图消息过滤与空态
- [ ] T008 运行 `apps/user-web` 的类型检查与单测（`pnpm -C apps/user-web test` / `typecheck`），确认零回归（SC-002）
- [ ] T009 目视验证：切 tab 不丢滚动、生成中切换不中断、多会话各自保持（quickstart.md）
- [ ] T010 更新 `docs/WORK_LOG.md`（日期 + 做了什么 + 改了哪些文件 + 验证方式）

## 依赖

- T002/T003/T004 可并行（[P]）
- T005 依赖 T001、T002、T003
- T007 依赖 T001；T008 依赖全部实现项

## 提交纪律

- 只 `git add` 本特性文件（T001–T007 列出的路径），**不**用 `git add -A`
- 工作区存在其他会话在途改动（`apps/user-web/pnpm-lock.yaml`、`apps/user-web/tests/code-platform-contract.test.ts` 等），一律不碰
